using UnityEngine;

namespace ShamwaySelfTest
{
    /// <summary>
    /// Worked reference for docs/authoring/environment-effects.md — "Save,
    /// clamp, restore". This pipeline ships tooling, not game-runtime code
    /// (ADR 0007), so this is a copy-paste example, not a vendored helper: copy
    /// it into your mod's own Harmony assembly and adapt the values. It is kept
    /// here, in the self-test fixture, so the doc's prose has a concrete,
    /// in-repo example to point at.
    ///
    /// These are global statics on the CLIENT, not per-effect state. Four rules,
    /// each with a visible failure when skipped:
    ///   * sentinels, not zero: forceClouds/forceRain/fogDebugDensity are -1f
    ///     and fogDebugColor is ignored under alpha 0; a "reset to zero" pins
    ///     the sky clear and dry and logs nothing.
    ///   * capture once on entry, never per-frame: the getters return your own
    ///     override while you force, so a per-frame re-capture ratchets the
    ///     effect to full within a few frames.
    ///   * clamp against the baseline (Mathf.Max/Min), never replace it; an
    ///     assignment erases a stronger vanilla storm.
    ///   * restore on effect-end AND on world change; the engine's Cleanup runs
    ///     on teardown only, so the walking-out case is yours.
    /// </summary>
    internal static class WeatherCapture
    {
        private static bool _entered;
        private static float _cloudBase, _rainBase, _fogBase, _lightBase;
        private static Color _fogColorBase;

        /// <summary>Snapshot the entry baseline once, before writing anything.</summary>
        private static void OnEnter()
        {
            if (_entered) return;
            _entered = true;
            _cloudBase = WeatherManager.GetCurrentCloudThicknessPercent();
            _rainBase = WeatherManager.GetCurrentRainfallPercent();
            _fogBase = SkyManager.fogDebugDensity;
            _fogColorBase = SkyManager.fogDebugColor;
            _lightBase = WeatherManager.weatherLightScale;
        }

        /// <summary>Clamp against the baseline and force the effect (client only).</summary>
        public static void Apply(float cloud, float rain, float fog, float light)
        {
            if (GameManager.IsDedicatedServer) return;
            OnEnter();
            // Max: never erase a stronger storm that existed at entry.
            WeatherManager.forceClouds = Mathf.Max(_cloudBase, cloud);
            WeatherManager.forceRain = Mathf.Max(_rainBase, rain);
            SkyManager.fogDebugDensity = Mathf.Max(_fogBase, fog);
            // Min: a thunderstorm must stay at least as bright as it was.
            WeatherManager.weatherLightScale = Mathf.Min(_lightBase, light);
        }

        /// <summary>Restore the sentinels; call from both the effect-end and world-change hooks.</summary>
        public static void OnExit()
        {
            WeatherManager.forceClouds = -1f;                 // sentinels, not 0
            WeatherManager.forceRain = -1f;
            SkyManager.fogDebugDensity = -1f;
            SkyManager.fogDebugColor = new Color(0f, 0f, 0f, 0f);
            WeatherManager.weatherLightScale = 1f;
            _entered = false;
        }
    }
}
