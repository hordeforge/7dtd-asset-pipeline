using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using UnityEditor;
using UnityEngine;

namespace SevenDaysToDie.AssetPipeline
{
    /// <summary>
    /// Marks a mod-owned method that must run before the bundle is collected.
    ///
    /// <para><b>Why this exists.</b> <c>BundleBuilder</c> is pipeline-owned: it
    /// carries the stem-collision rejection, the graphics-API set, and the
    /// forced rebuild, and a mod that edits it inherits none of the fixes. But
    /// most real mods generate part of their bundle from code — prefabs,
    /// materials, particle systems — and those generators have to run <i>before</i>
    /// the folder is collected, or the build ships whatever was there last
    /// time. Silently, because a stale prefab is a perfectly valid prefab.</para>
    ///
    /// <para>So the mod keeps its generators and the pipeline keeps its builder,
    /// and this attribute is the seam between them:</para>
    ///
    /// <code>
    /// [ShamwayPreBuild(Order = 10)]
    /// public static void EnsureGeneratedPrefabs() { ... }
    /// </code>
    ///
    /// <para>Order runs low to high; equal orders run in a stable alphabetical
    /// order, so a build is reproducible. Use it when one generator consumes
    /// another's materials.</para>
    ///
    /// <para>The method must be <c>static</c> and take no parameters. Anything
    /// it throws fails the build, which is the point: a generator that cannot
    /// run must not produce a bundle that looks finished.</para>
    /// </summary>
    [AttributeUsage(AttributeTargets.Method, AllowMultiple = false, Inherited = false)]
    public sealed class ShamwayPreBuildAttribute : Attribute
    {
        /// <summary>Ascending. Ties break alphabetically for a reproducible build.</summary>
        public int Order { get; set; }
    }

    /// <summary>Discovers and runs the mod's <see cref="ShamwayPreBuildAttribute"/> methods.</summary>
    public static class ShamwayPreBuild
    {
        /// <summary>
        /// The bundle-membership folder this build is collecting, as configured
        /// in `.shamway.toml`.
        ///
        /// <para>A generator has to write its output somewhere inside that
        /// folder, and hardcoding the path in the mod means the same value
        /// lives in two places and drifts the first time either moves. Read it
        /// from here instead. Set before any generator runs; null outside a
        /// build.</para>
        /// </summary>
        public static string SourceRoot { get; internal set; }

        /// <summary>
        /// Run every marked generator. Returns how many ran.
        ///
        /// Deliberately loud even when it finds nothing: "pre-build: 0 generators"
        /// in the log is the difference between a mod that has none and a mod
        /// whose attribute is on a method the compiler never saw.
        /// </summary>
        public static int RunAll()
        {
            var methods = Discover();
            Debug.Log("[shamway] pre-build: " + methods.Count + " generator(s)");
            foreach (var method in methods)
            {
                var name = method.DeclaringType?.FullName + "." + method.Name;
                Debug.Log("[shamway] pre-build: running " + name);
                try
                {
                    method.Invoke(null, null);
                }
                catch (TargetInvocationException exception)
                {
                    // Unwrap: the reflection wrapper hides the generator's own
                    // message, which is the only useful line in the log.
                    throw new Exception(
                        "Pre-build generator " + name + " failed: " + exception.InnerException?.Message,
                        exception.InnerException);
                }
            }
            if (methods.Count > 0)
            {
                AssetDatabase.SaveAssets();
                AssetDatabase.Refresh();
            }
            return methods.Count;
        }

        private static List<MethodInfo> Discover()
        {
            var found = new List<MethodInfo>();
            foreach (var method in TypeCache.GetMethodsWithAttribute<ShamwayPreBuildAttribute>())
            {
                var name = method.DeclaringType?.FullName + "." + method.Name;
                if (!method.IsStatic)
                    throw new Exception("[ShamwayPreBuild] " + name + " must be static.");
                if (method.GetParameters().Length != 0)
                    throw new Exception("[ShamwayPreBuild] " + name + " must take no parameters.");
                found.Add(method);
            }
            return found
                .OrderBy(method => method.GetCustomAttribute<ShamwayPreBuildAttribute>().Order)
                .ThenBy(method => method.DeclaringType?.FullName, StringComparer.Ordinal)
                .ThenBy(method => method.Name, StringComparer.Ordinal)
                .ToList();
        }
    }
}
