## What this does and why

<!-- Not just what changed -- the diff shows that. Why, and what broke/was missing before. -->

## Scope

<!-- One concern per PR (see CONTRIBUTING.md) -- a connector addition and an unrelated
     governance change are two PRs unless the second exists specifically to support the first. -->

- [ ] This PR is scoped to one concern.
- [ ] If it adds a connector: it's registered, has a `default_license` tag in
      `ingestion/quality_gates.KNOWN_LICENSES`, and — if it's a target-lookup/dual-use
      connector rather than a fixed public corpus — sets `requires_engagement = True`
      (see README's "Authorized pentesting connectors").

## Testing

<!-- What you ran, and what it showed. Every new connector, governance primitive, or bug fix
     needs a corresponding unit test -- see CONTRIBUTING.md. -->

- [ ] `docker compose -f docker/docker-compose.yml run --rm api python -m pytest tests/unit -v` passes
- [ ] `docker compose -f docker/docker-compose.yml run --rm api python -m ruff check src tests` passes
- [ ] Added/updated tests for the behavior this PR changes
- [ ] If this touches a live pipeline path (ingestion, retrieval, entity resolution), verified
      it against the real compose stack, not just unit tests — see README's "How to use it"

## Related issues

<!-- Closes #... -->
