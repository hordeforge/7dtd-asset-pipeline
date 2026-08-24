using System;
using System.Linq;
using UnityEditor;
using UnityEngine;

namespace SevenDaysToDie.AssetPipeline
{
    /// <summary>
    /// Loads a built or synthesized bundle with the engine's own loader and
    /// prints what came back, one line per asset.
    ///
    /// This is the check that is not self-graded: every other offline gate in
    /// this pipeline parses the artifact with a parser this project wrote,
    /// while <c>AssetBundle.LoadFromFile</c> is the call the game itself makes
    /// and <c>LoadAsset</c> deserializes with the engine's own class
    /// definitions. A bundle that loads here has a container and an object
    /// graph a runtime of this revision accepts.
    ///
    /// It is still not acceptance: it says nothing about whether the asset
    /// looks or sounds right, and nothing about 7 Days to Die's own loading
    /// path. That is a fresh client and a person.
    ///
    /// The output is parsed by <c>bundle_verify.py</c>, so the VERIFY- prefixes
    /// are a contract, not decoration.
    /// </summary>
    public static class BundleVerifier
    {
        // The camera setup is IconRenderer's, deliberately: that one is known to
        // produce a frame in batch mode, and an ad-hoc camera here reported
        // 100% coverage for a built-in cube as readily as for a bundle prefab -
        // a measurement that agreed with itself and would have convicted a
        // shader of this gate's own bug. ARGB32 and allowHDR=false are the two
        // details that differed.
        private const int DrawProbePixels = 128;

        /// <summary>Whether this run was asked to photograph prefabs.</summary>
        private static bool DrawRequested()
        {
            foreach (string argument in Environment.GetCommandLineArgs())
            {
                if (argument == "-shamwayDraw") { return true; }
            }
            return false;
        }

        /// <summary>Fraction of the frame a camera actually rasterized.</summary>
        private static double Coverage(Camera camera, RenderTexture target, Texture2D readback)
        {
            RenderTexture previous = RenderTexture.active;
            camera.Render();
            RenderTexture.active = target;
            readback.ReadPixels(new Rect(0f, 0f, DrawProbePixels, DrawProbePixels), 0, 0);
            readback.Apply();
            RenderTexture.active = previous;
            int drawn = 0;
            Color32[] pixels = readback.GetPixels32();
            foreach (Color32 pixel in pixels)
            {
                if (pixel.a > 8) { drawn++; }
            }
            return 100.0 * drawn / pixels.Length;
        }

        /// <summary>
        /// Photograph the prefab and report how much of the frame it filled.
        ///
        /// <para>Every other check here answers "did it load". A prefab can
        /// load with its mesh, material and shader all present and still
        /// rasterize nothing, or rasterize everywhere: a vertex shader reading
        /// its matrices from the wrong offsets puts the geometry somewhere the
        /// camera is not, and <c>Shader.isSupported</c> stays true throughout.
        /// Only a rendered frame can tell.</para>
        ///
        /// <para>Two zooms and a control, because one number proves nothing. A
        /// real object's coverage falls with the zoom; geometry ignoring the
        /// transform fills every frame; and a built-in cube rendered through
        /// the same camera says whether this measurement works at all before
        /// any of it is read as a verdict.</para>
        /// </summary>
        private static void ReportDrawn(string name, GameObject prefab)
        {
            GameObject instance = null;
            GameObject rig = null;
            GameObject control = null;
            RenderTexture target = null;
            Texture2D readback = null;
            try
            {
                instance = UnityEngine.Object.Instantiate(prefab);
                Bounds bounds = new Bounds(Vector3.zero, Vector3.one);
                bool any = false;
                foreach (Renderer each in instance.GetComponentsInChildren<Renderer>(true))
                {
                    if (any) { bounds.Encapsulate(each.bounds); } else { bounds = each.bounds; any = true; }
                }
                if (!any)
                {
                    Debug.LogError("VERIFY-FAIL: " + name + " has no renderer to draw");
                    return;
                }

                target = new RenderTexture(DrawProbePixels, DrawProbePixels, 24,
                                           RenderTextureFormat.ARGB32);
                readback = new Texture2D(DrawProbePixels, DrawProbePixels,
                                         TextureFormat.RGBA32, false);
                rig = new GameObject("shamway-verify-rig");
                Camera camera = rig.AddComponent<Camera>();
                camera.orthographic = true;
                camera.clearFlags = CameraClearFlags.SolidColor;
                camera.backgroundColor = new Color(0f, 0f, 0f, 0f);
                camera.allowHDR = false;
                camera.allowMSAA = false;
                camera.targetTexture = target;

                Quaternion view = Quaternion.Euler(20f, 205f, 0f);
                rig.transform.rotation = view;
                float radius = Mathf.Max(bounds.extents.magnitude, 0.001f);
                rig.transform.position = bounds.center - view * Vector3.forward * (radius * 4f);
                camera.nearClipPlane = 0.01f;
                camera.farClipPlane = radius * 12f;
                float framed = Mathf.Max(bounds.extents.x, bounds.extents.y, bounds.extents.z);
                camera.orthographicSize = framed * 1.4f;

                double near = Coverage(camera, target, readback);
                camera.orthographicSize = framed * 5.6f;
                double far = Coverage(camera, target, readback);

                // The control: a built-in cube of the same size, same camera,
                // same texture. If this does not behave, nothing below is a
                // verdict on the bundle.
                instance.SetActive(false);
                control = GameObject.CreatePrimitive(PrimitiveType.Cube);
                control.transform.position = bounds.center;
                control.transform.localScale = bounds.size;
                camera.orthographicSize = framed * 1.4f;
                double controlNear = Coverage(camera, target, readback);
                camera.orthographicSize = framed * 5.6f;
                double controlFar = Coverage(camera, target, readback);

                // A second control, wearing the bundle's own material on the
                // built-in cube. Between the two, a zero splits cleanly: a
                // built-in mesh that vanishes under this material accuses the
                // material and its shader; one that draws accuses the mesh.
                Material worn = null;
                foreach (Renderer each in instance.GetComponentsInChildren<Renderer>(true))
                {
                    if (each.sharedMaterial != null) { worn = each.sharedMaterial; break; }
                }
                double wornNear = -1.0;
                if (worn != null)
                {
                    // Ask the runtime whether the pass can be set up at all.
                    // `SetPass` returning false is the difference between "the
                    // shader loaded" and "the shader can draw", which
                    // `isSupported` does not distinguish.
                    Debug.Log("VERIFY-PASS: passCount=" + worn.passCount +
                              " SetPass(0)=" + worn.SetPass(0) +
                              " lightMode='" + worn.GetTag("LightMode", false, "<none>") +
                              "' renderType='" + worn.GetTag("RenderType", false, "<none>") + "'");
                    // Bypass the renderer entirely: set the pass by hand and
                    // issue the draw. This skips culling, sorting and
                    // LightMode pass selection, so it separates "the program
                    // does not rasterize" from "the renderer never issued the
                    // draw" - two faults that look identical from coverage.
                    try
                    {
                        Mesh cubeMesh = control.GetComponent<MeshFilter>().sharedMesh;
                        RenderTexture prev2 = RenderTexture.active;
                        RenderTexture.active = target;
                        GL.Clear(true, true, new Color(0f, 0f, 0f, 0f));
                        GL.PushMatrix();
                        GL.LoadIdentity();
                        GL.LoadProjectionMatrix(Matrix4x4.Ortho(-1f, 1f, -1f, 1f, -10f, 10f));
                        worn.SetPass(0);
                        Graphics.DrawMeshNow(cubeMesh, Matrix4x4.identity);
                        GL.PopMatrix();
                        readback.ReadPixels(new Rect(0f, 0f, DrawProbePixels, DrawProbePixels), 0, 0);
                        readback.Apply();
                        RenderTexture.active = prev2;
                        int lit = 0;
                        foreach (Color32 px in readback.GetPixels32()) { if (px.a > 8) { lit++; } }
                        Debug.Log("VERIFY-DRAWNOW: direct SetPass+DrawMeshNow covered=" +
                                  (100.0 * lit / (DrawProbePixels * DrawProbePixels)).ToString("0.0") + "%");
                    }
                    catch (Exception drawNowFailed)
                    {
                        Debug.Log("VERIFY-DRAWNOW: not measured (" + drawNowFailed.Message + ")");
                    }
                    // Validate this measurement path before trusting a zero
                    // from it: a material Unity built itself, on the same cube,
                    // measured the same way. If this reads zero, the probe is
                    // broken and the bundle's material is not accused.
                    Material builtIn = new Material(Shader.Find("Unlit/Texture"));
                    control.GetComponent<Renderer>().sharedMaterial = builtIn;
                    camera.orthographicSize = framed * 1.4f;
                    Debug.Log("VERIFY-DRAWN-BUILTIN-MAT: built-in cube wearing a fresh " +
                              "Unlit/Texture material covered=" +
                              Coverage(camera, target, readback).ToString("0.0") + "%");

                    control.GetComponent<Renderer>().sharedMaterial = worn;
                    camera.orthographicSize = framed * 1.4f;
                    wornNear = Coverage(camera, target, readback);

                    // Same material object, a shader Unity compiled itself.
                    // Separates "this Material is broken" from "the shader it
                    // points at is". Restored afterwards.
                    Shader wasShader = worn.shader;
                    worn.shader = Shader.Find("Unlit/Color");
                    camera.orthographicSize = framed * 1.4f;
                    Debug.Log("VERIFY-DRAWN-SWAPPED: the bundle's material wearing " +
                              "Unlit/Color covered=" +
                              Coverage(camera, target, readback).ToString("0.0") + "%");
                    worn.shader = wasShader;
                    Debug.Log("VERIFY-DRAWN-MATERIAL: built-in cube wearing '" + worn.name +
                              "' covered=" + wornNear.ToString("0.0") + "%");
                }
                instance.SetActive(true);

                Debug.Log("VERIFY-DRAWN-CONTROL: built-in cube covered=" +
                          controlNear.ToString("0.0") + "% zoomed-out=" + controlFar.ToString("0.0") + "%");
                bool controlSane = controlNear > 2.0 && controlNear < 99.0 && controlFar < controlNear;
                if (!controlSane)
                {
                    Debug.Log("VERIFY-DRAWN: " + name + " not measured (the control cube read " +
                              controlNear.ToString("0.0") + "%/" + controlFar.ToString("0.0") +
                              "%, so this host's offscreen render is not usable)");
                    return;
                }

                Debug.Log("VERIFY-DRAWN: " + name + " covered=" + near.ToString("0.0") +
                          "% zoomed-out=" + far.ToString("0.0") + "%");
                if (near <= 0.01)
                {
                    Debug.LogError("VERIFY-FAIL: " + name + " loaded but rasterized nothing, " +
                                   "while a built-in cube in the same frame drew " +
                                   controlNear.ToString("0.0") + "%.");
                }
                else if (near > 99.0 && far > 99.0)
                {
                    Debug.LogError("VERIFY-FAIL: " + name + " fills the frame at every zoom while " +
                                   "the control cube does not, so its geometry is not following " +
                                   "the camera transform. Suspect the vertex shader's " +
                                   "constant-buffer offsets.");
                }
            }
            catch (Exception error)
            {
                Debug.Log("VERIFY-DRAWN: " + name + " not measured (" + error.GetType().Name + ")");
            }
            finally
            {
                if (control != null) { UnityEngine.Object.DestroyImmediate(control); }
                if (rig != null) { UnityEngine.Object.DestroyImmediate(rig); }
                if (readback != null) { UnityEngine.Object.DestroyImmediate(readback); }
                if (target != null) { target.Release(); UnityEngine.Object.DestroyImmediate(target); }
                if (instance != null) { UnityEngine.Object.DestroyImmediate(instance); }
            }
        }

        public static void Verify()
        {
            string path = CommandLineValue("-bundle");
            if (string.IsNullOrEmpty(path))
            {
                Debug.LogError("VERIFY-FAIL: no -bundle argument");
                EditorApplication.Exit(2);
                return;
            }

            Debug.Log("VERIFY: loading " + path);
            AssetBundle bundle = AssetBundle.LoadFromFile(path);
            if (bundle == null)
            {
                // The runtime rejects a container it cannot use by returning
                // null rather than by throwing, which is exactly the failure
                // the class-142 gate exists to predict.
                Debug.LogError("VERIFY-FAIL: AssetBundle.LoadFromFile returned null");
                EditorApplication.Exit(3);
                return;
            }

            string[] names = bundle.GetAllAssetNames();
            Debug.Log("VERIFY: asset names = " + string.Join(", ", names));
            foreach (string name in names)
            {
                UnityEngine.Object asset = bundle.LoadAsset(name);
                if (asset == null)
                {
                    Debug.LogError("VERIFY-FAIL: could not load " + name);
                    bundle.Unload(true);
                    EditorApplication.Exit(4);
                    return;
                }

                Debug.Log("VERIFY-ASSET: " + name + " -> " + asset.GetType().Name +
                          " named '" + asset.name + "'");
                TextAsset text = asset as TextAsset;
                if (text != null)
                {
                    Debug.Log("VERIFY-TEXT: " + text.bytes.Length + " bytes");
                }

                Texture2D texture = asset as Texture2D;
                if (texture != null)
                {
                    Debug.Log("VERIFY-TEX: " + texture.width + "x" + texture.height + " " +
                              texture.format + " readable=" + texture.isReadable);
                }

                Shader shader = asset as Shader;
                if (shader != null)
                {
                    // isSupported is the engine's own verdict on a compiled
                    // shader: it is false when the runtime cannot find a
                    // sub-program it can use on this GPU and API, which is
                    // exactly how a hand-wrapped bytecode blob fails. A
                    // shader that loads is not a shader that runs.
                    // ...and it is only a verdict when there is a device to
                    // give it. Under -nographics this same shader reports
                    // isSupported=true passes=1, and with a real device
                    // isSupported=false passes=3: the headless answer is not a
                    // weaker measurement, it is a different question. This
                    // repository recorded the headless value as evidence that
                    // a synthesized shader runs. It is not evidence of that.
                    bool device = SystemInfo.graphicsDeviceType !=
                                  UnityEngine.Rendering.GraphicsDeviceType.Null;
                    Debug.Log("VERIFY-SHADER: '" + shader.name +
                              "' isSupported=" + shader.isSupported +
                              " passes=" + shader.passCount +
                              " renderQueue=" + shader.renderQueue +
                              " properties=" + shader.GetPropertyCount() +
                              " device=" + SystemInfo.graphicsDeviceType);
                    if (!device)
                    {
                        Debug.Log("VERIFY-SHADER-NOTE: no graphics device, so isSupported above " +
                                  "is not a verdict on this shader. Re-run with --draw (and " +
                                  "xvfb-run -a on a headless host) to get one.");
                    }
                    else if (!shader.isSupported)
                    {
                        Debug.LogError("VERIFY-FAIL: " + name +
                                       " loaded but the runtime reports it unsupported");
                    }
                }

                Material material = asset as Material;
                if (material != null)
                {
                    // A material whose shader failed to resolve silently
                    // becomes Unity's magenta error shader, which loads
                    // perfectly and renders wrong. Name it, so the report
                    // shows which shader the material actually bound.
                    string shaderName = material.shader != null ? material.shader.name : "<none>";
                    Texture mainTexture = material.HasProperty("_MainTex")
                        ? material.GetTexture("_MainTex") : null;
                    Debug.Log("VERIFY-MATERIAL: '" + material.name +
                              "' shader='" + shaderName +
                              "' shaderSupported=" + (material.shader != null && material.shader.isSupported) +
                              " _MainTex=" + (mainTexture != null ? mainTexture.name : "<unbound>") +
                              " renderQueue=" + material.renderQueue);
                    if (material.shader == null || shaderName == "Hidden/InternalErrorShader")
                    {
                        Debug.LogError("VERIFY-FAIL: " + name +
                                       " fell back to the internal error shader");
                    }
                }

                GameObject prefab = asset as GameObject;
                if (prefab != null)
                {
                    // A prefab is the thing 7DTD's Meshfile and Model actually
                    // load, so what matters is whether its renderer found a
                    // mesh and a material. A renderer with neither loads
                    // perfectly and draws nothing.
                    MeshFilter filter = prefab.GetComponent<MeshFilter>();
                    MeshRenderer renderer = prefab.GetComponent<MeshRenderer>();
                    string meshName = filter != null && filter.sharedMesh != null
                        ? filter.sharedMesh.name : "<none>";
                    int materials = renderer != null ? renderer.sharedMaterials.Length : 0;
                    Debug.Log("VERIFY-PREFAB: components=" + prefab.GetComponents<Component>().Length +
                              " mesh=" + meshName +
                              " materials=" + materials +
                              " children=" + prefab.transform.childCount);
                    if (filter != null && filter.sharedMesh == null)
                    {
                        Debug.LogError("VERIFY-FAIL: " + name + " has a MeshFilter with no mesh");
                    }
                    if (DrawRequested()) { ReportDrawn(name, prefab); }
                }

                Mesh mesh = asset as Mesh;
                if (mesh != null)
                {
                    // A mesh whose vertex stream or index buffer is malformed
                    // deserializes to zero counts rather than failing, which
                    // is the same shape of silence the clip check below covers.
                    Debug.Log("VERIFY-MESH: vertices=" + mesh.vertexCount +
                              " triangles=" + (mesh.triangles.Length / 3) +
                              " submeshes=" + mesh.subMeshCount +
                              " uv=" + (mesh.uv.Length > 0) +
                              " bounds=" + mesh.bounds.size);
                    if (mesh.vertexCount == 0 || mesh.triangles.Length == 0)
                    {
                        Debug.LogError("VERIFY-FAIL: " + name + " read back with no geometry");
                    }
                }

                AudioClip clip = asset as AudioClip;
                if (clip != null)
                {
                    // FMOD decodes the resource stream here. A clip whose bank
                    // is malformed reports zero samples rather than failing.
                    Debug.Log("VERIFY-CLIP: channels=" + clip.channels +
                              " frequency=" + clip.frequency +
                              " samples=" + clip.samples +
                              " seconds=" + clip.length);
                    if (clip.samples == 0)
                    {
                        Debug.LogError("VERIFY-FAIL: " + name + " decoded to zero samples");
                    }
                }

                // The game asks for an asset by its file-name stem, in the case
                // the XML wrote, not by the lowercased key the bundle lists. If
                // that lookup misses, every URI in the mod misses with it.
                string stem = System.IO.Path.GetFileNameWithoutExtension(name);
                if (bundle.LoadAsset(asset.name) == null && bundle.LoadAsset(stem) == null)
                {
                    Debug.LogError("VERIFY-FAIL: " + asset.name +
                                   " is not reachable by its own name, only as '" + name + "'");
                }
            }

            bundle.Unload(true);
            Debug.Log("VERIFY-OK");
            EditorApplication.Exit(0);
        }

        private static string CommandLineValue(string flag)
        {
            string[] args = Environment.GetCommandLineArgs();
            for (int index = 0; index < args.Length - 1; index++)
            {
                if (args[index] == flag)
                {
                    return args[index + 1];
                }
            }

            return null;
        }
    }
}
