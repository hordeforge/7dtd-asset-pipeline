using UnityEngine;

namespace ShamwaySelfTest
{
    /// <summary>
    /// This mod's own animal avatar controller. The asset pipeline's point is
    /// that the mod owns the model, the clips and the controller — so a
    /// generated creature does not lean on the stock
    /// `GameObjectAnimalAnimation`, whose `Awake` reads the legacy `Animation`
    /// off the model root's first active child *at AddComponent time*, which is
    /// during `EModelBase.Init` — before the generated model hierarchy is
    /// settled. That lookup returns null and `CreateEntity` NREs at
    /// `anim["Idle1"]` (the recorded spawn-time NRE), so a generated creature
    /// spawned by `spawnentity` never appears.
    ///
    /// This controller instead binds the figure's legacy `Animation` lazily on
    /// the first `Update` (after the model is fully instantiated), and then
    /// switches clips by motion state — `Idle1` when still, `Walk` when moving —
    /// the same convention the engine's animal controller uses, so a generated
    /// creature grounds and moves without a stock-controller dependency.
    /// </summary>
    public class ShamwayAnimalController : AvatarController
    {
        private Animation clipAnim;
        private Vector3 lastPos;
        private bool bound;

        public override void Awake()
        {
            // Intentionally do not touch the model here: the hierarchy is not
            // settled when AddComponent runs during model init. `lastPos` is
            // seeded on the first Update so the first motion sample is not a
            // huge jump from the spawn origin.
            bound = false;
        }

        public override void Update()
        {
            var e = entity;
            if (e == null)
            {
                return; // engine not finished wiring the controller to an entity
            }
            if (!bound)
            {
                Bind(e);
                bound = true;
            }

            Vector3 now = e.position;
            if (clipAnim == null)
            {
                lastPos = now;
                return; // no figure/clips: a generated model with no clips
            }

            float motion = (now - lastPos).magnitude;
            lastPos = now;

            // The engine's animal controller treats sustained motion as Walk
            // (and Idle1 otherwise). A tiny threshold keeps a barely-moving
            // creature from crossfading every frame.
            bool moving = motion > 0.0015f;
            string desired = moving ? "Walk" : "Idle1";
            AnimationState state = clipAnim[desired];
            if (state != null && !state.enabled)
            {
                clipAnim.CrossFade(desired, 0.5f);
            }
        }

        private void Bind(EntityAlive e)
        {
            // Figure is the model root's active child carrying the legacy
            // Animation. Find it by name first (the writer's `figure` node),
            // then by any descendant Animation, so a renamed or wrapped model
            // still binds.
            Transform figure = transform.Find("figure");
            clipAnim = figure != null ? figure.GetComponent<Animation>() : null;
            if (clipAnim == null)
            {
                clipAnim = GetComponentInChildren<Animation>();
            }
            lastPos = e.position;
        }

        public override bool IsAnimationAttackPlaying()
        {
            return false;
        }

        public override void StartAnimationAttack()
        {
            // No attack clips in the generated set; keep the idle/walk state.
        }

        public override Transform GetActiveModelRoot()
        {
            Transform figure = transform.Find("figure");
            return figure != null ? figure : transform;
        }

        public override void SetVisible(bool visible)
        {
            foreach (var r in GetComponentsInChildren<Renderer>(true))
            {
                r.enabled = visible;
            }
        }
    }
}
