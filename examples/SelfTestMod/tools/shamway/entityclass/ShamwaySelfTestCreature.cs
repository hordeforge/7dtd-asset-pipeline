using UnityEngine;

namespace ShamwaySelfTest
{
    /// <summary>
    /// This mod's own animal entity type. The asset pipeline's whole point is
    /// that the mod owns the model, the clips and the class — so a generated
    /// creature must not reuse a stock animal type (EntityAnimalStag/Snake),
    /// whose C# class brings a pre-authored model, a stock physics body with
    /// bone paths the generated rig does not have, and a template AITask
    /// wander that roams. This concrete EntityAlive subclass is the type the
    /// entityclass's `Class` names: the engine resolves it through
    /// `Type.GetType` (EntityClass IL), no stock expectations are inherited,
    /// and the generated prefab's own `Physics`-node capsule grounds it.
    /// </summary>
    public class ShamwaySelfTestCreature : EntityAlive
    {
        // A terminal, spawnable EntityAlive needs no overrides: the base
        // provides the move/ground/CC chain, AvatarController =
        // GameObjectAnimalAnimation (set in entityclasses.xml) plays the
        // legacy Animation clips the writer attaches to the figure child.
    }
}
