using System;
using System.IO;
using UnityEditor;
using UnityEngine;

namespace SevenDaysToDie.AssetPipeline
{
    /// <summary>
    /// Reusable helpers for authoring bundle assets from code instead of from
    /// unrecorded GUI state, so an agent or a script can regenerate a prefab
    /// deterministically.
    ///
    /// These wrap the operations that are easy to get subtly wrong in batch
    /// mode. Unity's material inspector performs side effects that assigning
    /// fields from a script does not, so a script-built material can carry a
    /// correct-looking texture that the shader never samples. Every trap
    /// encoded here corresponds to an entry in docs/troubleshooting.md.
    /// </summary>
    public static class GeneratedAsset
    {
        /// <summary>Create an AssetDatabase folder path, including parents.</summary>
        public static string EnsureFolder(string path)
        {
            if (AssetDatabase.IsValidFolder(path)) return path;
            var parent = Path.GetDirectoryName(path)?.Replace('\\', '/');
            var leaf = Path.GetFileName(path);
            if (string.IsNullOrEmpty(parent) || string.IsNullOrEmpty(leaf))
                throw new ArgumentException("Not a valid asset folder path: " + path);
            EnsureFolder(parent);
            AssetDatabase.CreateFolder(parent, leaf);
            return path;
        }

        /// <summary>
        /// Add a built-in primitive as a child of <paramref name="parent"/>.
        ///
        /// This is one of the two mesh lanes, and the one that needs nothing
        /// beyond Unity. Composing built-in primitives keeps the bundle free of
        /// class-43 Mesh objects entirely — the prefab references Unity's
        /// always-loaded default resources instead — so the geometry is a few
        /// numbers in a reviewable diff rather than a binary blob. It suits
        /// hard-surface props assembled from boxes, cylinders, and spheres.
        ///
        /// The other lane is an authored mesh from Blender or OpenSCAD, which
        /// is the right choice for organic, rigged, or sculpted geometry. Check
        /// those with `7dtd-assets check-mesh` before importing them.
        ///
        /// Sizes are metres. Unity's cube is 1 m at unit scale; its cylinder,
        /// sphere, and capsule are 2 m tall, so scale accordingly.
        /// </summary>
        public static GameObject Primitive(
            Transform parent,
            PrimitiveType type,
            string name,
            Vector3 position,
            Vector3 rotation,
            Vector3 scale,
            Material material)
        {
            var part = GameObject.CreatePrimitive(type);
            part.name = name;
            part.transform.SetParent(parent, false);
            part.transform.localPosition = position;
            part.transform.localEulerAngles = rotation;
            part.transform.localScale = scale;
            // CreatePrimitive attaches a collider to every part. 7DTD wants one
            // collider on the root, not one per visual piece, so strip them here
            // and add the root collider deliberately with RootCollider.
            var collider = part.GetComponent<Collider>();
            if (collider != null) UnityEngine.Object.DestroyImmediate(collider);
            if (material != null) part.GetComponent<MeshRenderer>().sharedMaterial = material;
            return part;
        }

        /// <summary>
        /// Create a prefab root with an identity transform.
        ///
        /// The root must stay at identity scale and rotation: the engine applies
        /// its own corrections after loading (item code applies a dropped
        /// correction rotation and DropScale), and a root that already carries a
        /// transform compounds with those instead of replacing them. Author the
        /// real dimensions on the child parts.
        /// </summary>
        public static GameObject Root(string name)
        {
            var root = new GameObject(name);
            root.transform.localPosition = Vector3.zero;
            root.transform.localRotation = Quaternion.identity;
            root.transform.localScale = Vector3.one;
            return root;
        }

        /// <summary>Add the single root collider a dropped or placed object needs.</summary>
        public static BoxCollider RootCollider(GameObject root, Vector3 center, Vector3 size)
        {
            var collider = root.AddComponent<BoxCollider>();
            collider.center = center;
            collider.size = size;
            return collider;
        }

        /// <summary>
        /// Scale every child of a root uniformly, leaving the root at identity.
        ///
        /// This is how one authored shape yields size variants without a second
        /// copy of its geometry, and without giving the root a transform the
        /// engine's own corrections would compound with.
        /// </summary>
        public static void ScaleChildren(GameObject root, float factor)
        {
            if (factor <= 0f) throw new ArgumentException("Scale factor must be positive.");
            foreach (Transform child in root.transform)
            {
                child.localPosition *= factor;
                child.localScale *= factor;
            }
        }

        /// <summary>Report a prefab's world bounds, so dimensions are reviewable in the log.</summary>
        public static Bounds MeasureBounds(GameObject root)
        {
            var renderers = root.GetComponentsInChildren<MeshRenderer>();
            if (renderers.Length == 0) return new Bounds(root.transform.position, Vector3.zero);
            var bounds = renderers[0].bounds;
            for (var index = 1; index < renderers.Length; index++)
                bounds.Encapsulate(renderers[index].bounds);
            return bounds;
        }

        /// <summary>
        /// Create or replace an opaque Standard material.
        ///
        /// Assigning _BumpMap or _MetallicGlossMap is not enough: the Standard
        /// shader samples them only when the matching keyword is enabled, and
        /// nothing enables it outside the inspector GUI.
        /// </summary>
        public static Material StandardMaterial(
            string assetPath,
            Color albedo,
            Texture2D albedoMap = null,
            Texture2D normalMap = null,
            Texture2D metallicGlossMap = null,
            float metallic = 0f,
            float smoothness = 0.5f)
        {
            var material = new Material(Shader.Find("Standard"));
            material.SetColor("_Color", albedo);
            material.SetFloat("_Metallic", metallic);
            material.SetFloat("_Glossiness", smoothness);
            if (albedoMap != null) material.SetTexture("_MainTex", albedoMap);
            if (normalMap != null)
            {
                material.SetTexture("_BumpMap", normalMap);
                material.EnableKeyword("_NORMALMAP");
            }
            if (metallicGlossMap != null)
            {
                material.SetTexture("_MetallicGlossMap", metallicGlossMap);
                // Standard ignores _Metallic and _Glossiness entirely once this
                // keyword is on; the map's own channels take over.
                material.EnableKeyword("_METALLICGLOSSMAP");
            }
            return Save(material, assetPath);
        }

        /// <summary>
        /// Create or replace a transparent material suitable for particles and
        /// alpha cards.
        ///
        /// Setting _Mode alone leaves the material opaque. Blend factors, depth
        /// write, keywords, and the render queue must all be set explicitly,
        /// because the inspector normally does that as a side effect of the
        /// dropdown and a batch script never touches the inspector.
        /// </summary>
        public static Material TransparentMaterial(
            string assetPath, Color tint, Texture2D mainTexture = null, bool additive = false)
        {
            var material = new Material(Shader.Find("Standard"));
            material.SetColor("_Color", tint);
            if (mainTexture != null) material.SetTexture("_MainTex", mainTexture);
            material.SetFloat("_Mode", 3f); // Transparent
            material.SetInt("_SrcBlend", (int)UnityEngine.Rendering.BlendMode.SrcAlpha);
            material.SetInt("_DstBlend", (int)(additive
                ? UnityEngine.Rendering.BlendMode.One
                : UnityEngine.Rendering.BlendMode.OneMinusSrcAlpha));
            material.SetInt("_ZWrite", 0);
            material.DisableKeyword("_ALPHATEST_ON");
            material.EnableKeyword("_ALPHABLEND_ON");
            material.DisableKeyword("_ALPHAPREMULTIPLY_ON");
            material.renderQueue = (int)UnityEngine.Rendering.RenderQueue.Transparent;
            return Save(material, assetPath);
        }

        /// <summary>
        /// Save a scene object as a prefab and destroy the temporary instance.
        ///
        /// The prefab file stem is what 7DTD resolves, so the root object is
        /// renamed to match: block model loading compares the loaded object's
        /// name and a mismatch produces a silent fallback mesh.
        /// </summary>
        public static GameObject SavePrefab(GameObject instance, string folder, string stem)
        {
            RequireBundleStem(stem);
            EnsureFolder(folder);
            instance.name = stem;
            var path = folder + "/" + stem + ".prefab";
            try
            {
                var prefab = PrefabUtility.SaveAsPrefabAsset(instance, path);
                if (prefab == null) throw new Exception("Could not save prefab: " + path);
                return prefab;
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(instance);
            }
        }

        /// <summary>
        /// Reject a stem that 7DTD cannot address unambiguously.
        ///
        /// The engine resolves bundle assets by file-name stem alone, dropping
        /// folder and extension, so a bare or generic name collides across the
        /// bundle. BundleBuilder rejects collisions at build time; this rejects
        /// the likely ones at authoring time, where the fix is cheap.
        /// </summary>
        public static void RequireBundleStem(string stem)
        {
            if (string.IsNullOrEmpty(stem))
                throw new ArgumentException("A bundle asset needs a non-empty file-name stem.");
            foreach (var character in stem)
                if (!char.IsLetterOrDigit(character) && character != '_' && character != '-')
                    throw new ArgumentException(
                        "Bundle stem '" + stem + "' must be letters, digits, '_', or '-'.");
            if (stem.Length < 4)
                throw new ArgumentException(
                    "Bundle stem '" + stem + "' is too short to be unique; prefix it with the mod name.");
        }

        private static Material Save(Material material, string assetPath)
        {
            var folder = Path.GetDirectoryName(assetPath)?.Replace('\\', '/');
            if (!string.IsNullOrEmpty(folder)) EnsureFolder(folder);
            var existing = AssetDatabase.LoadAssetAtPath<Material>(assetPath);
            if (existing != null)
            {
                // Replace in place so every prefab already referencing this
                // material keeps its reference across a regeneration.
                EditorUtility.CopySerialized(material, existing);
                UnityEngine.Object.DestroyImmediate(material);
                EditorUtility.SetDirty(existing);
                AssetDatabase.SaveAssets();
                return existing;
            }
            AssetDatabase.CreateAsset(material, assetPath);
            AssetDatabase.SaveAssets();
            return material;
        }
    }
}
