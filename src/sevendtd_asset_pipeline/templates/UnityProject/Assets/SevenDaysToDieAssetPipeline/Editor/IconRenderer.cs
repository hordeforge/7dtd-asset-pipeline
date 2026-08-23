using System;
using System.IO;
using UnityEditor;
using UnityEngine;

namespace SevenDaysToDie.AssetPipeline
{
    /// <summary>
    /// Photograph one prefab from the bundle into a transparent PNG, for use as
    /// an item-atlas icon.
    ///
    /// <para><b>Why this exists.</b> There are two honest ways to make an item
    /// icon. One is to draw or generate a picture of the item; the other is to
    /// render the item itself. The second cannot drift: regenerating the mesh
    /// regenerates the icon, and the thing in the backpack is the thing in the
    /// hand. Use it whenever the icon should simply <i>be</i> the item, and use
    /// generated art when the icon should show something the mesh does not.</para>
    ///
    /// <para>Deliberately not part of the bundle build. Icons live in
    /// <c>UIAtlases/&lt;Atlas&gt;/</c>, not in the asset bundle, and rendering is
    /// a rare authoring step rather than something every build should do.</para>
    ///
    /// <para><b>This one needs a graphics device.</b> Run it without
    /// <c>-nographics</c>. With that flag Unity executes this method happily,
    /// <c>Camera.Render()</c> draws nothing, and the output is a uniform
    /// transparent square that reads as a framing bug rather than a missing
    /// device. <c>shamway render-icon</c> launches it correctly.</para>
    /// </summary>
    public static class IconRenderer
    {
        /// <summary>
        /// Supersampling factor. The atlas cell is small and item geometry is
        /// often thin (an antenna, a wire, a fin); rendering large and letting a
        /// real resampler downscale is what keeps those from breaking into
        /// dashes. The downscale happens outside Unity, in the caller.
        /// </summary>
        public const int Supersample = 4;

        public static void RenderFromCommandLine()
        {
            int exitCode = 0;
            try
            {
                string prefabPath = Argument("-sapIconPrefab");
                string output = Argument("-sapIconOutput");
                if (prefabPath == null || output == null)
                    throw new Exception("-sapIconPrefab and -sapIconOutput are both required.");

                int pixels = int.Parse(Argument("-sapIconPixels") ?? "640");
                float yaw = float.Parse(Argument("-sapIconYaw") ?? "208");
                float pitch = float.Parse(Argument("-sapIconPitch") ?? "8");
                float padding = float.Parse(Argument("-sapIconPadding") ?? "1.22");

                // Regenerate first. An icon rendered from a stale prefab is the
                // specific way this lane fails: the render succeeds, the image
                // looks fine, and it shows the geometry from before the edit.
                Shamway.SourceRoot = Argument("-sapSourceRoot");
                Shamway.RunPreBuild();
                AssetDatabase.Refresh();
                Render(prefabPath, output, pixels, yaw, pitch, padding);
            }
            catch (Exception error)
            {
                Debug.LogError("[shamway] icon render failed: " + error);
                exitCode = 2;
            }
            EditorApplication.Exit(exitCode);
        }

        /// <param name="yaw">
        /// Camera yaw in degrees. The default is past 180 on purpose: the camera
        /// looks along its own forward vector, so a yaw near zero photographs the
        /// <i>back</i> of an item whose front detail faces +Z.
        /// </param>
        public static void Render(
            string prefabPath,
            string outputPath,
            int pixels,
            float yaw = 208f,
            float pitch = 8f,
            float padding = 1.22f)
        {
            GameObject prefab = AssetDatabase.LoadAssetAtPath<GameObject>(prefabPath);
            if (prefab == null) throw new FileNotFoundException("No prefab at " + prefabPath);

            GameObject instance = UnityEngine.Object.Instantiate(prefab);
            GameObject rig = new GameObject("sevenDaysToDieIconRig");
            RenderTexture target = new RenderTexture(pixels, pixels, 24, RenderTextureFormat.ARGB32)
            {
                antiAliasing = 8,
            };
            Texture2D readback = new Texture2D(pixels, pixels, TextureFormat.RGBA32, false);
            RenderTexture previous = RenderTexture.active;
            try
            {
                Bounds bounds = MeasureBounds(instance);

                Camera camera = rig.AddComponent<Camera>();
                camera.orthographic = true;
                camera.clearFlags = CameraClearFlags.SolidColor;
                // Zero alpha: the atlas needs the item cut out, not sitting on a card.
                camera.backgroundColor = new Color(0f, 0f, 0f, 0f);
                camera.allowHDR = false;
                camera.allowMSAA = true;
                camera.targetTexture = target;

                Quaternion view = Quaternion.Euler(pitch, yaw, 0f);
                rig.transform.rotation = view;
                float radius = bounds.extents.magnitude;
                rig.transform.position = bounds.center - view * Vector3.forward * (radius * 4f);
                camera.nearClipPlane = 0.01f;
                camera.farClipPlane = radius * 12f;

                // Frame from the extents as the camera sees them, not from the
                // bounding sphere: props are usually much wider than they are
                // tall, and sphere framing leaves the item floating in a mostly
                // empty cell.
                Vector3 extents = bounds.extents;
                float halfWidth = Mathf.Abs(Vector3.Dot(extents, view * Vector3.right));
                float halfHeight = Mathf.Max(
                    Mathf.Abs(Vector3.Dot(extents, view * Vector3.up)), Mathf.Abs(extents.y));
                camera.orthographicSize = Mathf.Max(halfWidth, halfHeight) * padding;

                // Three lights and a bright trilight ambient. Item materials are
                // usually dark — steel, tape, rubber — and lighting them like a
                // scene at dusk renders a silhouette. Exposure is a real decision:
                // half of these values crushes dark materials to black, twice them
                // washes them to pale grey.
                AddLight(rig.transform, new Vector3(26f, -24f, 0f), new Color(1f, 0.97f, 0.9f), 1.35f);
                AddLight(rig.transform, new Vector3(8f, 135f, 0f), new Color(0.66f, 0.74f, 0.88f), 0.6f);
                AddLight(rig.transform, new Vector3(-42f, 44f, 0f), new Color(0.95f, 0.88f, 0.76f), 0.4f);
                RenderSettings.ambientMode = UnityEngine.Rendering.AmbientMode.Trilight;
                RenderSettings.ambientSkyColor = new Color(0.34f, 0.36f, 0.42f);
                RenderSettings.ambientEquatorColor = new Color(0.26f, 0.26f, 0.28f);
                RenderSettings.ambientGroundColor = new Color(0.14f, 0.14f, 0.13f);

                camera.Render();
                RenderTexture.active = target;
                readback.ReadPixels(new Rect(0f, 0f, pixels, pixels), 0, 0);
                readback.Apply();

                string folder = Path.GetDirectoryName(Path.GetFullPath(outputPath));
                if (!string.IsNullOrEmpty(folder)) Directory.CreateDirectory(folder);
                File.WriteAllBytes(outputPath, readback.EncodeToPNG());
                Debug.Log("[shamway] rendered " + prefabPath + " -> " + outputPath
                    + " (" + pixels + " px)");
            }
            finally
            {
                RenderTexture.active = previous;
                UnityEngine.Object.DestroyImmediate(readback);
                target.Release();
                UnityEngine.Object.DestroyImmediate(target);
                UnityEngine.Object.DestroyImmediate(rig);
                UnityEngine.Object.DestroyImmediate(instance);
            }
        }

        private static Bounds MeasureBounds(GameObject instance)
        {
            Renderer[] renderers = instance.GetComponentsInChildren<Renderer>();
            if (renderers.Length == 0)
                throw new Exception(instance.name + " has no renderers to photograph.");
            Bounds bounds = renderers[0].bounds;
            for (int index = 1; index < renderers.Length; index++)
                bounds.Encapsulate(renderers[index].bounds);
            return bounds;
        }

        private static void AddLight(Transform parent, Vector3 euler, Color color, float intensity)
        {
            GameObject node = new GameObject("iconLight");
            node.transform.SetParent(parent, false);
            node.transform.localEulerAngles = euler;
            Light light = node.AddComponent<Light>();
            light.type = LightType.Directional;
            light.color = color;
            light.intensity = intensity;
            light.shadows = LightShadows.None;
        }

        private static string Argument(string name)
        {
            string[] args = Environment.GetCommandLineArgs();
            for (int index = 0; index < args.Length - 1; index++)
                if (args[index] == name) return args[index + 1];
            return null;
        }
    }
}
