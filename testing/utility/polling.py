def trigger_poll(user, subscription_ids=None):
    """Run the active view's polling coordinator immediately."""
    return user.page.evaluate(
        """async (ids) => {
            const view = document.querySelector("[lp-view]")?._lp_view;
            if (!view?.PollingCoordinator) {
                throw new Error("The active view has no polling coordinator");
            }
            return await view.PollingCoordinator.trigger(ids);
        }""",
        subscription_ids,
    )
