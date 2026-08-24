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
