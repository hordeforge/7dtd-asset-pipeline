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
        /// those with `shamway check-mesh` before importing them.
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
            // CreatePrimitive attaches a collider to every part. EntityItem.createMesh
            // (V 3.1.0 b14, ilspycmd) enables *every* collider it finds in a dropped
            // item's mesh on layer 13, so each visual piece would become a physics
            // body. Strip them here and add one root collider deliberately with
            // RootCollider or RootCapsuleCollider.
            var collider = part.GetComponent<Collider>();
            if (collider != null) UnityEngine.Object.DestroyImmediate(collider);
            if (material != null) part.GetComponent<MeshRenderer>().sharedMaterial = material;
            return part;
        }

        /// <summary>
        /// Create a prefab root with an identity transform.
        ///
        /// The root must stay at identity scale and rotation: the engine applies
        /// its own transform after loading. EntityItem.createMesh (V 3.1.0 b14,
        /// ilspycmd) *overwrites* the instantiated root's localScale with
        /// DropScale and its localRotation with the dropped correction, so a
        /// scale authored on the root is silently discarded rather than
        /// compounded. Author the real dimensions on the child parts, and size
        /// variants with ScaleChildren.
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
        /// The capsule variant, which is what vanilla's held-item prefabs carry
        /// (GrenadePrefab has one root CapsuleCollider). A dropped item rolls
        /// and settles more naturally on a capsule than on a box.
        /// </summary>
        public static CapsuleCollider RootCapsuleCollider(
            GameObject root, Vector3 center, float radius, float height, int direction = 1)
        {
            var collider = root.AddComponent<CapsuleCollider>();
            collider.center = center;
            collider.radius = radius;
            collider.height = height;
            collider.direction = direction;   // 0 = X, 1 = Y (upright), 2 = Z
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
                // One packed texture feeds two slots: Standard reads metallic from
                // _MetallicGlossMap.r, smoothness from .a, and occlusion from
                // _OcclusionMap.g. Without this second assignment the G channel
                // the texture-maps generator writes is never sampled.
                material.SetTexture("_OcclusionMap", metallicGlossMap);
                material.SetFloat("_OcclusionStrength", 1f);
            }
            return Save(material, assetPath);
        }

        /// <summary>
        /// Tile a material's maps, for a flat-colour part that borrows a
        /// tileable detail normal (texture-maps detail) instead of an albedo.
        ///
        /// Standard shares one scale/offset across _MainTex, _BumpMap and
        /// _MetallicGlossMap, so the tiling is set once on _MainTex. Choose the
        /// repeat from the part's real size: a 512 px steel normal authored at
        /// roughly 0.25 m per tile wants a 4x repeat on a one-metre face.
        /// </summary>
        public static Material Tile(Material material, float repeatU, float repeatV)
        {
            material.mainTextureScale = new Vector2(repeatU, repeatV);
            EditorUtility.SetDirty(material);
            AssetDatabase.SaveAssets();
            return material;
        }

        /// <summary>
        /// Create or replace an emissive Standard material, for an indicator
        /// lamp or a lit panel.
        ///
        /// _EmissionColor alone does nothing: the Standard shader samples
        /// emission only under the _EMISSION keyword, which the inspector
        /// enables when a colour is chosen and nothing enables in batch mode.
        /// The GI flag is set too, or a baked lighting pass ignores the lamp.
        /// Intensity above 1 is how an LED reads as lit rather than painted.
        /// </summary>
        public static Material EmissiveMaterial(
            string assetPath, Color albedo, Color emission, float intensity = 2.4f,
            float smoothness = 0.6f)
        {
            var material = new Material(Shader.Find("Standard"));
            material.SetColor("_Color", albedo);
            material.SetFloat("_Metallic", 0f);
            material.SetFloat("_Glossiness", smoothness);
            material.SetColor("_EmissionColor", emission * intensity);
            material.EnableKeyword("_EMISSION");
            material.globalIlluminationFlags = MaterialGlobalIlluminationFlags.RealtimeEmissive;
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

        // ------------------------------------------------------------------
        // Texture imports
        //
        // A map has two ways to be wrong that produce no error, no warning and
        // no log line: the shader keyword (handled in the material helpers
        // above) and the *import type*. A normal map imported as a Default
        // texture reaches the shader as raw colour, and a mask imported as sRGB
        // has every metallic and smoothness value bent by the colour
        // transform. Both render something plausible, which is what makes them
        // expensive.
        // ------------------------------------------------------------------

        /// <summary>
        /// Import a texture as a tangent-space normal map.
        ///
        /// Note that <c>convertToNormalMap</c> lives on
        /// <see cref="TextureImporterSettings"/>, reached through
        /// ReadTextureSettings/SetTextureSettings — it is not a property of
        /// TextureImporter in 2022.3, and assuming it is costs a failed batch
        /// build whose only shell symptom is "Scripts have compiler errors".
        /// </summary>
        public static Texture2D ImportNormalMap(string assetPath, int maxSize = 1024)
        {
            var importer = AssetImporter.GetAtPath(assetPath) as TextureImporter;
            if (importer == null) throw new FileNotFoundException("No texture at " + assetPath);
            var settings = new TextureImporterSettings();
            importer.ReadTextureSettings(settings);
            settings.textureType = TextureImporterType.NormalMap;
            settings.convertToNormalMap = false;   // the file already IS a normal map
            settings.sRGBTexture = false;
            importer.SetTextureSettings(settings);
            importer.maxTextureSize = maxSize;
            importer.SaveAndReimport();
            return AssetDatabase.LoadAssetAtPath<Texture2D>(assetPath);
        }

        /// <summary>
        /// Import a texture as linear data: a packed metallic/occlusion/
        /// smoothness mask, a height map, anything whose channels are
        /// measurements rather than colour.
        /// </summary>
        public static Texture2D ImportLinearMap(string assetPath, int maxSize = 512)
        {
            var importer = AssetImporter.GetAtPath(assetPath) as TextureImporter;
            if (importer == null) throw new FileNotFoundException("No texture at " + assetPath);
            importer.textureType = TextureImporterType.Default;
            importer.sRGBTexture = false;
            importer.maxTextureSize = maxSize;
            importer.SaveAndReimport();
            return AssetDatabase.LoadAssetAtPath<Texture2D>(assetPath);
        }

        /// <summary>Import a colour texture: albedo, an emissive map, a particle card.</summary>
        public static Texture2D ImportColorMap(string assetPath, int maxSize = 1024, bool alpha = true)
        {
            var importer = AssetImporter.GetAtPath(assetPath) as TextureImporter;
            if (importer == null) throw new FileNotFoundException("No texture at " + assetPath);
            importer.textureType = TextureImporterType.Default;
            importer.sRGBTexture = true;
            importer.alphaIsTransparency = alpha;
            importer.maxTextureSize = maxSize;
            importer.SaveAndReimport();
            return AssetDatabase.LoadAssetAtPath<Texture2D>(assetPath);
        }

        // ------------------------------------------------------------------
        // Particles
        // ------------------------------------------------------------------

        /// <summary>
        /// Create or replace a Particles/Standard Unlit material in a real
        /// blend state.
        ///
        /// <para>Setting <c>_Mode</c> is not enough, and this is the single
        /// most expensive material trap in the pipeline. <c>_Mode</c> is read by
        /// the shader's <i>inspector GUI</i>, which is what normally applies the
        /// blend factors, depth write, keywords, and render queue — and no GUI
        /// runs in a batch build. A card built by a script therefore stays in
        /// the shader's default <b>opaque</b> state and renders as a flat
        /// polygon with hard black edges, while every offline check passes.
        /// This mirrors Unity's own
        /// StandardParticleShaderGUI.SetupMaterialWithBlendMode.</para>
        ///
        /// <para>The mode numbers matter too: that shader enumerates
        /// <c>Opaque, Cutout, Fade, Transparent, Additive, Subtractive,
        /// Modulate</c>, so a plausible-looking <c>additive ? 2 : 0</c> actually
        /// asks for Fade and Opaque.</para>
        ///
        /// <para>Verify by reading the built .mat rather than by trusting the
        /// assignment: additive is _SrcBlend 5 / _DstBlend 1, fade is 5 / 10,
        /// and both want _ZWrite 0 and render queue 3000.</para>
        /// </summary>
        public static Material ParticleMaterial(
            string assetPath, Color tint, Texture2D card, bool additive = false)
        {
            var shader = Shader.Find("Particles/Standard Unlit");
            if (shader == null)
                throw new Exception(
                    "Particles/Standard Unlit is missing. Declare "
                    + "com.unity.modules.particlesystem in Packages/manifest.json.");
            var material = new Material(shader);
            material.SetColor("_Color", tint);
            if (card != null) material.SetTexture("_MainTex", card);
            material.SetFloat("_Mode", additive ? 4f : 2f);   // Additive : Fade
            material.SetInt("_SrcBlend", (int)UnityEngine.Rendering.BlendMode.SrcAlpha);
            material.SetInt("_DstBlend", (int)(additive
                ? UnityEngine.Rendering.BlendMode.One
                : UnityEngine.Rendering.BlendMode.OneMinusSrcAlpha));
            material.SetInt("_ZWrite", 0);
            material.SetFloat("_Cutoff", 0f);
            material.DisableKeyword("_ALPHATEST_ON");
            material.EnableKeyword("_ALPHABLEND_ON");
            material.DisableKeyword("_ALPHAPREMULTIPLY_ON");
            material.DisableKeyword("_ALPHAMODULATE_ON");
            material.EnableKeyword("_ALPHAOVERLAY_ON");
            material.renderQueue = (int)UnityEngine.Rendering.RenderQueue.Transparent;
            return Save(material, assetPath);
        }

        /// <summary>
        /// A zero-valued curve, for an axis of a module that must not move.
        ///
        /// <c>velocityOverLifetime</c> requires all three axes to share one
        /// MinMaxCurve mode. Assigning a plain float to x or z while y is a
        /// curve makes them Constant against a Curve, and Unity logs
        /// "Particle Velocity curves must all be in the same mode" on <i>every
        /// update</i> — thousands of lines a second in the client, and nothing
        /// at all offline.
        /// </summary>
        public static ParticleSystem.MinMaxCurve ZeroCurve()
        {
            return new ParticleSystem.MinMaxCurve(1f, AnimationCurve.Constant(0f, 1f, 0f));
        }

        /// <summary>
        /// Sum every system's maxParticles and reject a prefab over budget.
        ///
        /// A cap belongs in the prefab, not only in the runtime code that picks
        /// which prefab to spawn: a distance LOD that selects the cheap tier is
        /// no protection if the cheap tier was never actually cheap. Call this
        /// before saving, so an over-budget effect fails the build rather than
        /// a player's frame time.
        /// </summary>
        public static int BudgetParticles(GameObject root, int allowance)
        {
            var total = 0;
            foreach (var system in root.GetComponentsInChildren<ParticleSystem>(true))
                total += system.main.maxParticles;
            if (total > allowance)
                throw new Exception(
                    root.name + " allows " + total + " live particles, over its budget of "
                    + allowance + ". Lower maxParticles, or raise the budget deliberately.");
            return total;
        }

        // ------------------------------------------------------------------
        // Audio
        // ------------------------------------------------------------------

        /// <summary>
        /// Import an AudioClip for the bundle.
        ///
        /// <c>preloadAudioData</c> is off and loading is streamed for anything
        /// long, because a bundle opens lazily and a multi-megabyte clip
        /// decompressed at load stalls the frame it lands on.
        /// </summary>
        public static AudioClip ImportAudioClip(string assetPath, bool stream = false)
        {
            var importer = AssetImporter.GetAtPath(assetPath) as AudioImporter;
            if (importer == null) throw new FileNotFoundException("No audio clip at " + assetPath);
            var settings = importer.defaultSampleSettings;
            settings.loadType = stream
                ? AudioClipLoadType.Streaming
                : AudioClipLoadType.DecompressOnLoad;
            settings.compressionFormat = AudioCompressionFormat.Vorbis;
            settings.quality = 0.7f;
            // Per-platform since 2022.2. The old AudioImporter.preloadAudioData is
            // [Obsolete(..., error: true)] on 2022.3.62f2 (ilspycmd on
            // UnityEditor.dll), so touching it fails the whole project's editor
            // compile as "Scripts have compiler errors".
            settings.preloadAudioData = false;
            importer.defaultSampleSettings = settings;
            importer.forceToMono = true;   // 7DTD positions sounds in 3D itself
            importer.SaveAndReimport();
            return AssetDatabase.LoadAssetAtPath<AudioClip>(assetPath);
        }

        /// <summary>
        /// A mod-owned AudioSource prefab, for a sound that must carry further
        /// than a vanilla one.
        ///
        /// <c>Audio.Manager.LoadAudio</c> plays nothing at all beyond the
        /// AudioSource prefab's <c>maxDistance</c>, so a kilometre-scale event
        /// referencing a grenade-scale vanilla source is simply silent out
        /// there — before any DistantClip or fade setting gets a say. Build one
        /// of these, put it in the bundle, and name it in the sound group's
        /// AudioSource element.
        ///
        /// Logarithmic rolloff is the default because linear rolloff over a
        /// kilometre is audible as a fade rather than as distance.
        /// </summary>
        public static GameObject AudioSourcePrefab(
            string folder,
            string stem,
            float maxDistance = 1200f,
            float minDistance = 12f,
            AudioRolloffMode rolloff = AudioRolloffMode.Logarithmic)
        {
            var root = Root(stem);
            var source = root.AddComponent<AudioSource>();
            source.playOnAwake = false;
            source.spatialBlend = 1f;          // fully 3D; 0 would ignore position
            source.dopplerLevel = 0f;
            source.rolloffMode = rolloff;
            source.minDistance = minDistance;
            source.maxDistance = maxDistance;
            return SavePrefab(root, folder, stem);
        }

        /// <summary>
        /// A Light prefab for a particle system's Lights module.
        ///
        /// The Lights module needs a Light *prefab asset*, not a component, and
        /// that prefab is a bundle member only the particle module references:
        /// no XML names it, so list its stem in .shamway.toml
        /// `code_references` or validate cannot see it. Keep range and
        /// intensity modest and let the module's intensity curve do the pulse
        /// (lights.intensityMultiplier is a float; the curve goes on
        /// lights.intensity — assigning a MinMaxCurve where a float is expected
        /// fails the whole build as "Scripts have compiler errors").
        /// </summary>
        public static GameObject LightPrefab(
            string folder, string stem, Color color, float range = 60f, float intensity = 4f)
        {
            var root = Root(stem);
            var light = root.AddComponent<Light>();
            light.type = LightType.Point;
            light.color = color;
            light.range = range;
            light.intensity = intensity;
            light.shadows = LightShadows.None;
            return SavePrefab(root, folder, stem);
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
