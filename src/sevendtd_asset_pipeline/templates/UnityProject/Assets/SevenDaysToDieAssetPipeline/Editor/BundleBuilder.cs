using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;

namespace SevenDaysToDie.AssetPipeline
{
    /// <summary>Deterministic, batch-friendly asset-bundle builder for 7DTD.</summary>
    public static class BundleBuilder
    {
        private const string ProbeFolder = "Assets/SevenDaysToDieAssetPipeline/Probe";
        private const string ProbeAssetName = "sevenDaysToDiePipelineProbe";
        private const string ProbeBundleName = "seven-days-to-die-pipeline-probe.unity3d";

        public static void BuildFromCommandLine()
        {
            var exitCode = 0;
            try
            {
                var args = Environment.GetCommandLineArgs();
                var output = RequiredArg(args, "-sapOutput");
                var targetName = ArgValue(args, "-sapTarget") ?? "StandaloneWindows64";
                var probe = args.Contains("-sapProbe");
                var bundleName = probe ? ProbeBundleName : RequiredArg(args, "-sapBundleName");
                var sourceRoot = probe ? ProbeFolder : RequiredArg(args, "-sapSourceRoot");
                if (!Enum.TryParse(targetName, false, out BuildTarget target))
                    throw new Exception("Unknown BuildTarget '" + targetName + "'.");
                Build(target, output, bundleName, sourceRoot, probe);
            }
            catch (Exception exception)
            {
                Debug.LogError("[shamway] build failed: " + exception);
                exitCode = 2;
            }
            EditorApplication.Exit(exitCode);
        }

        private static void Build(BuildTarget target, string output, string bundleName, string sourceRoot, bool probe)
        {
            if (!EditorUserBuildSettings.SwitchActiveBuildTarget(BuildTargetGroup.Standalone, target))
                throw new Exception("Could not switch active build target to " + target + ".");
            if (probe) CreateProbe();
            try
            {
                // A probe deliberately skips this: it proves the environment
                // with a throwaway cube and must not run the mod's generators.
                if (!probe) ShamwayPreBuild.RunAll();
                var assets = CollectAssets(sourceRoot);
                if (assets.Length == 0)
                    throw new Exception("No assets found below " + sourceRoot + ".");
                RejectAmbiguousStems(assets);
                Directory.CreateDirectory(output);
                var build = new AssetBundleBuild { assetBundleName = bundleName, assetNames = assets };
                BuildWindowsBundle(build, output, target);
                var built = Path.Combine(output, bundleName);
                if (!File.Exists(built)) throw new Exception("Expected output is missing: " + built);
                Debug.Log("[shamway] built " + bundleName + " with " + assets.Length + " assets");
                foreach (var asset in assets) Debug.Log("[shamway] asset: " + asset);
            }
            finally
            {
                if (probe) DeleteProbe();
            }
        }

        private static void BuildWindowsBundle(AssetBundleBuild build, string output, BuildTarget target)
        {
            var oldDefaultApis = PlayerSettings.GetUseDefaultGraphicsAPIs(target);
            var oldApis = PlayerSettings.GetGraphicsAPIs(target);
            var oldStrip = PlayerSettings.stripEngineCode;
            try
            {
                PlayerSettings.stripEngineCode = false;
                PlayerSettings.SetUseDefaultGraphicsAPIs(target, false);
                PlayerSettings.SetGraphicsAPIs(target, new[] {
                    GraphicsDeviceType.Direct3D11,
                    GraphicsDeviceType.OpenGLCore,
                    GraphicsDeviceType.Vulkan,
                });
                var manifest = BuildPipeline.BuildAssetBundles(
                    output,
                    new[] { build },
                    BuildAssetBundleOptions.ChunkBasedCompression |
                    BuildAssetBundleOptions.StrictMode |
                    BuildAssetBundleOptions.ForceRebuildAssetBundle,
                    target);
                if (manifest == null) throw new Exception("BuildAssetBundles returned no manifest.");
            }
            finally
            {
                PlayerSettings.SetGraphicsAPIs(target, oldApis);
                PlayerSettings.SetUseDefaultGraphicsAPIs(target, oldDefaultApis);
                PlayerSettings.stripEngineCode = oldStrip;
            }
        }

        private static string[] CollectAssets(string root)
        {
            if (!AssetDatabase.IsValidFolder(root)) return Array.Empty<string>();
            return AssetDatabase.FindAssets(string.Empty, new[] { root })
                .Select(AssetDatabase.GUIDToAssetPath)
                .Where(path => !string.IsNullOrEmpty(path) && !AssetDatabase.IsValidFolder(path))
                .Where(path => !path.EndsWith(".meta", StringComparison.OrdinalIgnoreCase))
                .Where(path => Path.GetFileName(path) != ".gitkeep")
                .Distinct().OrderBy(path => path, StringComparer.Ordinal).ToArray();
        }

        private static void RejectAmbiguousStems(string[] assets)
        {
            var collisions = assets
                .GroupBy(Path.GetFileNameWithoutExtension, StringComparer.OrdinalIgnoreCase)
                .Where(group => group.Count() > 1)
                .Select(group => group.Key + ": " + string.Join(", ", group)).ToList();
            if (collisions.Count > 0)
                throw new Exception("7DTD resolves assets by file-name stem; collisions:\n  " +
                    string.Join("\n  ", collisions));
        }

        private static void CreateProbe()
        {
            EnsureFolder("Assets/SevenDaysToDieAssetPipeline", "Probe");
            var probe = GameObject.CreatePrimitive(PrimitiveType.Cube);
            try
            {
                probe.name = ProbeAssetName;
                PrefabUtility.SaveAsPrefabAsset(probe, ProbeFolder + "/" + ProbeAssetName + ".prefab");
            }
            finally { UnityEngine.Object.DestroyImmediate(probe); }
            AssetDatabase.Refresh();
        }

        private static void DeleteProbe()
        {
            if (AssetDatabase.IsValidFolder(ProbeFolder)) AssetDatabase.DeleteAsset(ProbeFolder);
            AssetDatabase.Refresh();
        }

        private static void EnsureFolder(string parent, string child)
        {
            var path = parent + "/" + child;
            if (!AssetDatabase.IsValidFolder(path)) AssetDatabase.CreateFolder(parent, child);
        }

        private static string RequiredArg(string[] args, string name)
        {
            return ArgValue(args, name) ?? throw new Exception("Missing required argument " + name + ".");
        }

        private static string ArgValue(string[] args, string name)
        {
            for (var index = 0; index < args.Length - 1; index++)
                if (args[index] == name) return args[index + 1];
            return null;
        }
    }
}
