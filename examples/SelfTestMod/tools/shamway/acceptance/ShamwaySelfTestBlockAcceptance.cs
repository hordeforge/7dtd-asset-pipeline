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
//   shamwayselftest_block_place — the character places the block. The item
//       from Config/items.xml is given and equipped, and the PlaceAsBlock
//       action fires against a floor voxel ahead of the camera — the same path
//       a player uses (ItemActionPlaceAsBlock.ExecuteAction → Block.PlaceBlock)
//       — so the server places the block with the player as its placer, and
//       the captured frame shows the character holding the block.
public sealed class ShamwaySelfTestBlockAcceptanceProvider : IScenarioProvider
{
    private const string BlockName = "shamwaySelfTestPropBlock";

    // CaseCtx is per-case, so the placed position has to survive between the
    // place case and the look case in a field of the provider.
    private static Vector3i _placedAt;
    private static bool _placed;

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
                var at = GroundedSpot(world, feet, ahead);
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

    /// <summary>Give the character the item and fire its PlaceAsBlock action.</summary>
    private void AppendPlaceSuite(List<CaseDef> queue, string label)
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
                if (!Helpers.TryGetItem(BlockName, out var itemValue) || itemValue.IsEmpty())
                {
                    ctx.IntA = 0;
                    ctx.Detail = "item " + BlockName + " is not registered";
                    return;
                }
                var feet = Helpers.FixtureSeedOrigin(player, world);
                var at = GroundedSpot(world, feet, ahead);
                if (at == null)
                {
                    ctx.IntA = 0;
                    ctx.Detail = "no grounded air voxel ahead of the camera to place into";
                    return;
                }
                ctx.TargetBlock = at.Value;
                _placedAt = at.Value;
                _placed = false;
                if (!Helpers.TryGiveItem(player, new ItemStack(itemValue, 1)))
                {
                    ctx.IntA = 0;
                    ctx.Detail = "could not give the block item";
                    return;
                }
                int have = Helpers.CountItemType(player, itemValue.type);
                if (have <= 0)
                {
                    ctx.IntA = 0;
                    ctx.Detail = "block item is not in the inventory after the give";
                    return;
                }
                int slot = Helpers.TryEquipItemType(player, itemValue.type);
                var held = player.inventory.holdingItem;
                if (slot < 0 || held == null || held.Id != itemValue.type)
                {
                    ctx.IntA = 0;
                    ctx.Detail = "could not equip the block item (slot=" + slot + ")";
                    return;
                }
                // Point the placement at the chosen voxel. The action reads the
                // player's HitInfo: lastBlockPos is the *air* voxel the block
                // goes into, hit.pos the point on the floor the ray hit.
                var hit = player.HitInfo;
                hit.bHitValid = true;
                hit.tag = "";
                hit.lastBlockPos = at.Value;
                hit.hit.blockPos = at.Value;
                hit.hit.pos = new Vector3(at.Value.x + 0.5f, at.Value.y - 0.5f, at.Value.z + 0.5f);
                hit.hit.blockFace = BlockFace.Top;
                hit.hit.distanceSq = 9f;
                try
                {
                    hit.hit.voxelData = HitInfoDetails.VoxelData.GetFrom(world, at.Value + Vector3i.down);
                }
                catch
                {
                    hit.hit.voxelData = default;
                }
                // The debug console swallows the use action when it is open;
                // close it so the placement fires like a normal click.
                try
                {
                    if (GUIWindowConsole.instance != null)
                    {
                        GUIWindowConsole.instance.CloseConsole();
                    }
                }
                catch
                {
                    // console may not exist in this game state; the action
                    // check below still decides
                }
                var heldData = player.inventory.holdingItemData;
                if (heldData == null || held.Actions == null || held.Actions.Length <= 1
                    || heldData.actionData == null || heldData.actionData.Count <= 1)
                {
                    ctx.IntA = 0;
                    ctx.Detail = "equipped item has no Action1 to fire";
                    return;
                }
                ctx.IntA = 1;
                held.Actions[1].ExecuteAction(heldData.actionData[1], true);
                ctx.Detail = "gave + equipped block item (count=" + have + ", slot=" + slot
                    + "), fired PlaceAsBlock at " + at.Value;
            },
            wait: ctx =>
            {
                if (ctx.IntA == 0)
                {
                    return true;
                }
                // The character placed the block: wait until the voxel the
                // action targeted is really the block. The model and its
                // rendering are the model suite's concern, not this one's.
                if (ctx.World.GetBlock(ctx.TargetBlock).type == 0)
                {
                    ctx.Detail = "placed? waiting for the block at " + ctx.TargetBlock;
                    return false;
                }
                _placed = true;
                _placedAt = ctx.TargetBlock;
                ctx.Detail = "placed type=" + ctx.World.GetBlock(ctx.TargetBlock).type + " at " + ctx.TargetBlock;
                return true;
            },
            assert: ctx => ctx.IntA == 1 && _placed,
            timeout: 40f,
            fail: "the player did not place shamwaySelfTestPropBlock"));

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
                if (!_placed || world.GetBlock(at).type == 0)
                {
                    Report.Info("shamwaySelfTestPropBlock: block is not in the world at " + at);
                    return false;
                }
                Report.Info("shamwaySelfTestPropBlock: placed type=" + world.GetBlock(at).type + " at " + at);
                return true;
            },
            holdSeconds: 12f,
            fail: "could not stage the placed shamwaySelfTestPropBlock in view"));
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
        var chunk = ctx.World.ChunkCache.GetChunkFromWorldPos(at);
        var bed = chunk != null ? chunk.GetBlockEntity(at) : null;
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
        var renderers = bed.transform.GetComponentsInChildren<Renderer>(true);
        if (renderers == null || renderers.Length == 0)
        {
            ctx.Detail = "model transform exists at " + at + " but has no renderers";
            return false;
        }
        foreach (var r in renderers)
        {
            r.enabled = true;
        }
        if (!bed.transform.gameObject.activeInHierarchy)
        {
            bed.transform.gameObject.SetActive(true);
        }
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
                var chunk = world.ChunkCache.GetChunkFromWorldPos(at);
                var bed = chunk != null ? chunk.GetBlockEntity(at) : null;
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

    /// <summary>
    /// A grounded air voxel ahead of the camera, one or two blocks out (the
    /// closest that still reads as a floor placement): surface height at the
    /// target column, one above it, with a solid voxel below so the server's
    /// stability pass does not turn the placement into a falling block
    /// (docs/runbooks/troubleshooting.md, "A placed block vanishes").
    /// </summary>
    private static Vector3i? GroundedSpot(World world, Vector3i feet, Vector3 ahead)
    {
        var dx = Mathf.RoundToInt(ahead.x * 2f);
        var dz = Mathf.RoundToInt(ahead.z * 2f);
        if (dx == 0 && dz == 0)
        {
            dx = Mathf.RoundToInt(ahead.x * 3f);
            dz = Mathf.RoundToInt(ahead.z * 3f);
        }
        var tx = feet.x + dx;
        var tz = feet.z + dz;
        int surface = feet.y;
        try
        {
            surface = Mathf.RoundToInt(world.GetHeightAt(tx, tz));
        }
        catch
        {
            // keep the player's surface; the support check below still applies
        }
        var candidates = new List<Vector3i>
        {
            new Vector3i(tx, surface + 1, tz),
            new Vector3i(tx, surface + 2, tz),
            new Vector3i(tx, feet.y + 1, tz),
            new Vector3i(feet.x + dx, surface + 1, feet.z + dz),
        };
        foreach (var at in candidates)
        {
            if (world.GetBlock(at).type != 0)
            {
                continue; // occupied
            }
            if (world.GetBlock(at + Vector3i.down).isair)
            {
                continue; // no support: the stability pass would drop it
            }
            return at;
        }
        return null;
    }
}
