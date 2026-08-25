using System.Collections.Generic;
using UnityEngine;
using ZdtdPlaytest;

// The block acceptance, as two separate suites beside the generated
// bundle-loading provider (ShamwaySelfTestAcceptance.cs, rewritten on every
// acceptance run — so this provider lives in its own file, per the pipeline's
// contract: "Write your own IScenarioProvider alongside the generated one").
//
//   shamwayselftest_block_model — the block's ModelEntity model renders. The
//       block is placed through the server and the suite waits until the
//       spawned prefab's renderer exists, then captures it. This is the Vulkan
//       render verification: does the block's model draw (where the generated
//       look case instantiates the prefab directly, bypassing the block)?
//
//   shamwayselftest_block_place — the character places the block. The block's
//       implicit item (ItemClassBlock; the mod ships no items.xml, so the
//       block behaves like a frame: outline preview and all) is given and
//       equipped, and the right-click use — Action1, which ItemClassBlock
//       routes to IBlockTool.ExecuteUseAction — fires while aiming at the
//       floor ahead, the same input path a player's click takes.
public sealed class ShamwaySelfTestBlockAcceptanceProvider : IScenarioProvider
{
    private const string BlockName = "shamwaySelfTestPropBlock";

    // CaseCtx is per-case, so the placed position has to survive between the
    // place case and the look case in a field of the provider.
    private static Vector3i _placedAt;
    private static bool _placed;
    private static float _lastClick;

    public IEnumerable<string> SuiteIds
    {
        get
        {
            yield return "shamwayselftest_block_model";
            yield return "shamwayselftest_block_place";
        }
    }

    public void AppendSuite(List<CaseDef> queue, string suite, int lap)
    {
        string label = lap > 0 ? suite + "@" + lap : suite;
        if (suite == "shamwayselftest_block_model")
        {
            AppendModelSuite(queue, label);
        }
        else if (suite == "shamwayselftest_block_place")
        {
            AppendPlaceSuite(queue, label);
        }
    }

    /// <summary>Place the block through the server; wait for its model.</summary>
    private void AppendModelSuite(List<CaseDef> queue, string label)
    {
        queue.Add(CaseDef.Live(label, "place_shamwaySelfTestPropBlock", new[] { "block", "setblock" },
            act: ctx =>
            {
                var player = ctx.Player;
                var world = ctx.World;
                if (player == null || world == null)
                {
                    ctx.Detail = "no player or world";
                    return;
                }
                var bv = Block.GetBlockValue(BlockName, true);
                if (bv.isair || bv.Block == null)
                {
                    ctx.IntA = 0;
                    ctx.Detail = "block " + BlockName + " is not registered";
                    return;
                }
                var camera = player.playerCamera != null
                    ? player.playerCamera.transform
                    : player.transform;
                var ahead = camera.forward;
                ahead.y = 0f;
                if (ahead.sqrMagnitude < 0.01f)
                {
                    ahead = player.transform.forward;
                    ahead.y = 0f;
                }
                ahead.Normalize();
                var feet = Helpers.FixtureSeedOrigin(player, world);
                var at = Helpers.FindGroundedAir(world, feet, ahead);
                if (at == null)
                {
                    ctx.IntA = 0;
                    ctx.Detail = "no grounded air voxel ahead of the camera to place into";
                    return;
                }
                ctx.TargetBlock = at.Value;
                _placedAt = at.Value;
                _placed = false;
                ctx.IntA = 1;
                Helpers.SetBlockRpc(world, at.Value, bv);
                ctx.Detail = "place rpc " + BlockName + " at " + at.Value;
            },
            wait: ctx =>
            {
                if (ctx.IntA == 0)
                {
                    return true;
                }
                return WaitForBlockAndModel(ctx);
            },
            assert: ctx => ctx.IntA == 1 && _placed,
            timeout: 40f,
            fail: "the block did not place or its model did not spawn"));

        AppendLookCase(queue, label);
    }

    /// <summary>The character genuinely places the block: give and equip the
    /// item, aim at the floor a couple of meters ahead, and drive the real use
    /// action (UseHoldingItem) every tick until the engine's own placement ray
    /// lands the block. No fabricated HitInfo, no direct ExecuteAction.</summary>
    private void AppendPlaceSuite(List<CaseDef> queue, string label)
    {
        queue.Add(CaseDef.Live(label, "place_shamwaySelfTestPropBlock", new[] { "block", "place" },
            act: ctx =>
            {
                var player = ctx.Player;
                var world = ctx.World;
                if (player == null || world == null)
                {
                    ctx.Detail = "no player or world";
                    return;
                }
                var bv = Block.GetBlockValue(BlockName, true);
                if (bv.isair || bv.Block == null)
                {
                    ctx.IntA = 0;
                    ctx.Detail = "block " + BlockName + " is not registered";
                    return;
                }
                if (!Helpers.TryGetItem(BlockName, out var itemValue) || itemValue.IsEmpty())
                {
                    ctx.IntA = 0;
                    ctx.Detail = "item " + BlockName + " is not registered";
                    return;
                }
                var camera = player.playerCamera != null
                    ? player.playerCamera.transform
                    : player.transform;
                var ahead = camera.forward;
                ahead.y = 0f;
                if (ahead.sqrMagnitude < 0.01f)
                {
                    ahead = player.transform.forward;
                    ahead.y = 0f;
                }
                ahead.Normalize();
                // The aim target is a floor voxel a couple of meters ahead of
                // the feet, one below eye level: looking at its center points
                // the character slightly down at the ground. It is only where
                // the character looks - where the block lands is whatever the
                // engine's placement ray decides, and the wait scans for it.
                var feet = Helpers.FixtureSeedOrigin(player, world);
                var aheadPoint = new Vector3(feet.x + 0.5f, 0f, feet.z + 0.5f) + ahead * 2f;
                ctx.TargetBlock = new Vector3i(
                    Mathf.FloorToInt(aheadPoint.x), feet.y - 1, Mathf.FloorToInt(aheadPoint.z));
                _placed = false;
                _lastClick = 0f;
                if (!Helpers.TryGiveItem(player, new ItemStack(itemValue, 1)))
                {
                    ctx.IntA = 0;
                    ctx.Detail = "could not give the block item";
                    return;
                }
                if (Helpers.TryEquipItemType(player, itemValue.type) < 0)
                {
                    ctx.IntA = 0;
                    ctx.Detail = "could not equip the block item";
                    return;
                }
                // An open window or debug console swallows the use action.
                Helpers.TryCloseWindows();
                Helpers.CloseDebugConsole();
                ctx.IntA = 1;
                ctx.IntB = itemValue.type;
                ctx.Detail = "gave + equipped " + BlockName + ", aiming at the floor " + ctx.TargetBlock;
            },
            wait: ctx =>
            {
                if (ctx.IntA == 0)
                {
                    return true;
                }
                var player = ctx.Player;
                var world = ctx.World;
                var bv = Block.GetBlockValue(BlockName, true);
                // Landed? Scan the floor around the aim point for the shamway
                // block's own type - never "any non-air voxel".
                var found = FindPlacedBlock(world, ctx.TargetBlock, bv.type);
                if (found != null)
                {
                    _placed = true;
                    _placedAt = found.Value;
                    ctx.Detail = "player placed type=" + bv.type + " at " + found.Value;
                    return true;
                }
                // Re-drive the real player path, the mining probe's loop:
                // equip, aim at the floor, click. Throttled to ~1s per click -
                // ItemActionPlaceAsBlock rejects uses closer together than its
                // Delay/cBuildIntervall, and spamming every tick just churns
                // the aim before the engine's ray settles on the floor.
                var held = player.inventory.holdingItem;
                if (held == null || held.Id != ctx.IntB)
                {
                    if (Helpers.TryEquipItemType(player, ctx.IntB) < 0)
                    {
                        ctx.Detail = "waiting for the block item to reach the held slot";
                        return false;
                    }
                }
                if (Time.unscaledTime - _lastClick < 1f)
                {
                    return false;
                }
                _lastClick = Time.unscaledTime;
                Helpers.LookAt(player, ctx.TargetBlock.ToVector3Center());
                // A held block's place is the right-click - but NOT through
                // UseHoldingItem: that indexes holdingItem.Actions[1], which
                // the implicit ItemClassBlock item leaves null, so the call is
                // a silent no-op. The real input path (PlayerMoveController's
                // click) is ItemClass.ExecuteAction(1, data, pressed,
                // playerActions), which ItemClassBlock overrides into
                // IBlockTool.ExecuteUseAction - and the tool places on the
                // PRESS (release returns immediately) and dereferences
                // playerActions unconditionally, so the real primary-player
                // input object is required, not null.
                try
                {
                    var heldClass = player.inventory.holdingItem;
                    var heldData = player.inventory.holdingItemData;
                    var actions = Platform.PlatformManager.NativePlatform.Input.PrimaryPlayer;
                    heldClass.ExecuteAction(1, heldData, false, actions);
                }
                catch (System.Exception ex)
                {
                    ctx.Detail = "use threw: " + ex.GetType().Name + " " + ex.Message;
                    return false;
                }
                // Diagnostic only: what the engine's own look ray sees, and
                // which of ExecuteAction's silent gates would reject it. The
                // placement still reads HitInfo itself; nothing is written.
                string ray = "ray=?";
                try
                {
                    var hi = player.HitInfo;
                    if (hi != null && hi.bHitValid)
                    {
                        var target = hi.lastBlockPos;
                        var tb = world.GetBlock(target);
                        ray = "ray block=" + target + " tag=" + hi.tag
                            + " targetAir=" + tb.isair
                            + " distSq=" + hi.hit.distanceSq
                            + "/" + bv.Block.GetPlacementDistanceSq()
                            + " canPlace=" + bv.Block.CanPlaceBlockAt(world, target, bv, false);
                    }
                    else
                    {
                        ray = "ray invalid";
                    }
                }
                catch (System.Exception ex) { ray = "ray err " + ex.Message; }
                ctx.Detail = "clicked " + BlockName + " aimed at " + ctx.TargetBlock + ", " + ray;
                return false;
            },
            assert: ctx => ctx.IntA == 1 && _placed
                && ctx.World.GetBlock(_placedAt).type == Block.GetBlockValue(BlockName, true).type,
            timeout: 40f,
            fail: "the player's use action did not place " + BlockName));

        // The character placed the block; hold the scene for the capture. This
        // suite only asserts the placement - how the model looks is the model
        // suite's verdict.
        queue.Add(CaseDef.Staged(label, "look_shamwaySelfTestPropBlock", new[] { "capture", "block" },
            stage: ctx =>
            {
                var player = ctx.Player;
                var world = ctx.World;
                if (player == null || world == null)
                {
                    Report.Info("shamwaySelfTestPropBlock: no player or world to stage around");
                    return false;
                }
                var at = _placedAt;
                var bv = Block.GetBlockValue(BlockName, true);
                if (!_placed || world.GetBlock(at).type != bv.type)
                {
                    Report.Info("shamwaySelfTestPropBlock: block is not in the world at " + at);
                    return false;
                }
                // Frame the placed block: look at the voxel the player placed.
                Helpers.LookAt(player, at.ToVector3Center());
                Report.Info("shamwaySelfTestPropBlock: placed type=" + world.GetBlock(at).type + " at " + at);
                return true;
            },
            holdSeconds: 12f,
            fail: "could not stage the placed shamwaySelfTestPropBlock in view"));
    }

    /// <summary>Scan the floor around the aim point for the block's type.</summary>
    private static Vector3i? FindPlacedBlock(World world, Vector3i center, int type)
    {
        for (int dy = -1; dy <= 2; dy++)
        {
            for (int dx = -3; dx <= 3; dx++)
            {
                for (int dz = -3; dz <= 3; dz++)
                {
                    var p = new Vector3i(center.x + dx, center.y + dy, center.z + dz);
                    if (world.GetBlock(p).type == type)
                    {
                        return p;
                    }
                }
            }
        }
        return null;
    }

    /// <summary>Wait until the block is in the world and its model spawned.</summary>
    private static bool WaitForBlockAndModel(CaseCtx ctx)
    {
        var at = ctx.TargetBlock;
        if (ctx.World.GetBlock(at).type == 0)
        {
            return false; // not placed, or it fell: keep waiting
        }
        // The model is not spawned by the placement itself: the chunk
        // instantiates it in a deferred display pass
        // (Chunk.OnDisplayBlockEntities -> GameObjectPool) that walks its
        // block-entity stubs with a per-call budget, so a freshly placed stub
        // at the end of a long list can take a while to reach. The stub is
        // visible the moment the pass creates its transform.
        var bed = Helpers.BlockEntityDataAt(ctx.World, at);
        if (bed == null || bed.transform == null)
        {
            if (ctx.IntB == 0)
            {
                ctx.IntB = 1;
                Report.Info("shamwaySelfTestPropBlock: placed type=" + ctx.World.GetBlock(at).type
                    + ", waiting for the chunk display pass to reach the stub at " + at);
            }
            ctx.Detail = "placed type=" + ctx.World.GetBlock(at).type + ", waiting for model near " + at;
            return false;
        }
        // The display pass places the model at a chunk-local position under the
        // origin parent, which lands it off to the side and above the block
        // (measured: "too high up and too far right"). Reposition it into the
        // camera's space - 1.5m ahead, just below eye level - so the playtest
        // capture frames it well. The camera transform lives in the origin-
        // relative scene space, so the target must be computed from it, never
        // from the block's absolute coordinates.
        var camera = ctx.Player != null && ctx.Player.playerCamera != null
            ? ctx.Player.playerCamera.transform
            : (ctx.Player != null ? ctx.Player.transform : null);
        if (camera != null)
        {
            var ahead = camera.forward;
            ahead.y = 0f;
            if (ahead.sqrMagnitude < 0.01f)
            {
                ahead = camera.forward;
            }
            ahead.Normalize();
            var want = camera.position + ahead * 1.5f;
            want.y = camera.position.y - 0.5f;
            bed.transform.position = want;
        }
        // The display pass may have left the renderers disabled (collision-only
        // mesh); switch them on so the model actually draws.
        if (!Helpers.ActivateBlockEntityModel(bed))
        {
            ctx.Detail = "model transform exists at " + at + " but has no renderers";
            return false;
        }
        var renderers = bed.transform.GetComponentsInChildren<Renderer>(true);
        _placed = true;
        _placedAt = at;
        ctx.Detail = "placed type=" + ctx.World.GetBlock(at).type + " model=" + renderers[0].name
            + " renderers=" + renderers.Length + " at " + at;
        return true;
    }

    /// <summary>Hold the placed block in front of the camera for the capture.</summary>
    private void AppendLookCase(List<CaseDef> queue, string label)
    {
        queue.Add(CaseDef.Staged(label, "look_shamwaySelfTestPropBlock", new[] { "capture", "block" },
            stage: ctx =>
            {
                var player = ctx.Player;
                var world = ctx.World;
                if (player == null || world == null)
                {
                    Report.Info("shamwaySelfTestPropBlock: no player or world to stage around");
                    return false;
                }
                var at = _placedAt;
                if (!_placed || world.GetBlock(at).type == 0)
                {
                    Report.Info("shamwaySelfTestPropBlock: block is not in the world at " + at);
                    return false;
                }
                // The model was repositioned in front of the camera by the
                // place case; verify its renderers are still live.
                var bed = Helpers.BlockEntityDataAt(world, at);
                var modelRenderers = bed != null && bed.transform != null
                    ? bed.transform.GetComponentsInChildren<Renderer>(true)
                    : null;
                if (modelRenderers == null || modelRenderers.Length == 0)
                {
                    Report.Info("shamwaySelfTestPropBlock: placed but the model has no live renderers");
                    return false;
                }
                Report.Info("shamwaySelfTestPropBlock: model at " + modelRenderers[0].transform.position
                    + " renderers=" + modelRenderers.Length);
                return true;
            },
            holdSeconds: 12f,
            fail: "could not stage the placed shamwaySelfTestPropBlock in view"));
    }

}
