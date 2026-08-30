using System.Collections.Generic;
using UnityEngine;
using ZdtdPlaytest;

// Hierarchy, skin and VFX load cases beside the generated bundle provider.
// Find armedLamp by name, count SkinnedMeshRenderer bones, instantiate the
// particle prefab. Mechanical only: this suite is not a picture.
//
// The looping burst prefab is judged by eye in shamwayselftest_look (the
// generated look_burst hold). That suite instantiates in front of the camera
// and must never share a PLAYTEST_SUITE list with *_block_*. Do not put a
// CaseDef.Staged instantiate here "so the VFX rides along with the block".
// Particles that are part of a built prefab are one object; a floating
// prefab next to a placed block is two pictures.
public sealed class ShamwaySelfTestEditorlessAcceptanceProvider : IScenarioProvider
{
    private const string Bundle =
        "#@modfolder(ShamwaySelfTest):Resources/shamwayselftest.unity3d";

    public IEnumerable<string> SuiteIds
    {
        get { yield return "shamwayselftest_editorless"; }
    }

    public void AppendSuite(List<CaseDef> queue, string suite, int lap)
    {
        string label = lap > 0 ? suite + "@" + lap : suite;

        Transform lamp = null;
        queue.Add(CaseDef.Live(label, "find_armedLamp", new[] { "bundle", "hierarchy" },
            act: ctx =>
            {
                var loaded = DataLoader.LoadAsset<GameObject>(Bundle + "?timedNuke");
                lamp = loaded == null ? null : FindNamed(loaded.transform, "armedLamp");
                Report.Info(lamp == null
                    ? "timedNuke: armedLamp not found"
                    : "timedNuke: armedLamp at " + lamp.name
                        + " parent=" + (lamp.parent == null ? "" : lamp.parent.name));
            },
            assert: ctx => lamp != null && lamp.name == "armedLamp",
            fail: "the hierarchy prefab has no child named armedLamp"));

        int boneCount = 0;
        int nullBones = -1;
        string rootName = "";
        queue.Add(CaseDef.Live(label, "skinned_bones_bound", new[] { "bundle", "skin" },
            act: ctx =>
            {
                var loaded = DataLoader.LoadAsset<GameObject>(Bundle + "?gear");
                var smr = loaded == null
                    ? null
                    : loaded.GetComponentInChildren<SkinnedMeshRenderer>(true);
                if (smr == null || smr.bones == null)
                {
                    Report.Info("gear: no SkinnedMeshRenderer");
                    return;
                }
                boneCount = smr.bones.Length;
                nullBones = 0;
                for (int i = 0; i < smr.bones.Length; i++)
                {
                    if (smr.bones[i] == null)
                    {
                        nullBones++;
                    }
                }
                rootName = smr.rootBone == null ? "" : smr.rootBone.name;
                Report.Info("gear: bones=" + boneCount + " nulls=" + nullBones
                    + " root=" + (rootName.Length == 0 ? "null" : rootName)
                    + " mesh=" + (smr.sharedMesh == null ? "null" : smr.sharedMesh.name));
            },
            assert: ctx => boneCount == 2 && nullBones == 0 && rootName == "Hips",
            fail: "the skinned prefab did not resolve both bones and a Hips root"));

        int systems = 0;
        int renderers = 0;
        bool instantiated = false;
        queue.Add(CaseDef.Live(label, "particles_instantiate", new[] { "bundle", "vfx" },
            act: ctx =>
            {
                var loaded = DataLoader.LoadAsset<GameObject>(Bundle + "?burst");
                if (loaded == null)
                {
                    Report.Info("burst: LoadAsset<GameObject> returned null");
                    return;
                }
                systems = loaded.GetComponentsInChildren<ParticleSystem>(true).Length;
                renderers = loaded.GetComponentsInChildren<ParticleSystemRenderer>(true).Length;
                var inst = Object.Instantiate(loaded);
                instantiated = inst != null;
                if (inst != null)
                {
                    Object.Destroy(inst);
                }
                Report.Info("burst: systems=" + systems + " renderers=" + renderers
                    + " instantiated=" + instantiated);
            },
            assert: ctx => systems >= 2 && renderers == systems && instantiated,
            fail: "the vfx prefab did not instantiate with matching ParticleSystem graphs"));
    }

    static Transform FindNamed(Transform root, string name)
    {
        if (root == null)
        {
            return null;
        }
        if (root.name == name)
        {
            return root;
        }
        for (int i = 0; i < root.childCount; i++)
        {
            var hit = FindNamed(root.GetChild(i), name);
            if (hit != null)
            {
                return hit;
            }
        }
        return null;
    }
}
