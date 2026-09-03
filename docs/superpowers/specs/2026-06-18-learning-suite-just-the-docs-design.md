# Learning Suite Just the Docs Design

## Goal

Create a new standalone GitHub repository for a personal learning suite published with GitHub Pages using the Just the Docs theme.

The site should work first as a personal notebook/wiki: quick to update, easy to browse, and comfortable for notes that are useful before they are polished. It should also include a small projects area so finished experiments can later become public proof-of-work.

## Scope

This design covers the initial repository scaffold, site structure, navigation, starter content, and local verification approach.

In scope:

- A new standalone repository named `learning-suite`.
- A Just the Docs based GitHub Pages site.
- A topic-oriented notes section.
- A projects section for learning experiments.
- A snippets section for reusable commands or code fragments.
- A resources section for external links and references.
- A learning log for weekly or dated progress notes.
- Basic GitHub Pages deployment guidance.

Out of scope for the first version:

- User accounts, comments, analytics, or private content controls.
- Custom JavaScript-heavy features.
- Automated content ingestion from other note systems.
- A custom visual design beyond theme configuration and simple branding.
- Migration of existing notes from outside this repository.

## Recommended Approach

Use a notebook-first information architecture with a light projects lane.

This keeps the site useful during day-to-day learning because notes can be short, unfinished, and linked by topic. Projects stay separate so completed work can be highlighted without forcing every note to become a polished portfolio entry.

## Repository Structure

The new repository should start with this shape:

```text
learning-suite/
  README.md
  _config.yml
  index.md
  notes/
    index.md
    git.md
    python.md
    data.md
    web.md
  projects/
    index.md
    first-project.md
  snippets/
    index.md
  resources/
    index.md
  log/
    index.md
```

## Site Navigation

Use the Just the Docs navigation order fields so the sidebar stays predictable:

1. Home
2. Notes
3. Projects
4. Snippets
5. Resources
6. Learning Log

Topic pages should live under `notes/`. Project pages should live under `projects/`. Snippets and resources can start as single index pages and split into subpages later if they grow.

## Homepage

The homepage should behave like a dashboard rather than a marketing page.

It should include:

- A short statement of what the learning suite is.
- A current focus section.
- Links to main sections.
- A short list of recent or featured notes.
- A short list of featured projects.

The copy should be plain and personal. The first version does not need elaborate branding.

## Content Model

Notes should be small and easy to maintain. A useful note can contain:

- What I learned.
- Why it matters.
- Example commands or code.
- Gotchas.
- Related links.

Project pages should be slightly more structured:

- Goal.
- What I built or tested.
- What I learned.
- Links to code, notes, or screenshots if available.
- Next steps.

Learning log entries can start as dated bullet lists on `log/index.md`. They can move to separate dated pages later if the log gets long.

## GitHub Pages Deployment

Use the standard GitHub Pages flow supported by Just the Docs. The first version should avoid a custom GitHub Actions workflow unless a later build requirement makes it necessary.

The first implementation should use the simplest path that works for a public GitHub repository:

- Keep the site source at the repository root.
- Configure `_config.yml` for Just the Docs.
- Add a minimal `Gemfile` for local preview and predictable Jekyll dependencies.
- Document the GitHub Pages settings needed after pushing the repository.
- Use the default GitHub Pages domain for the initial launch.

## Local Development

The implementation should include a minimal `Gemfile` and enough setup for local preview if Ruby/Jekyll is available:

```text
bundle install
bundle exec jekyll serve
```

If local Ruby tooling is not installed, the repository should still be usable through GitHub Pages after push.

## Verification

Before considering the scaffold complete:

- Confirm the Markdown files are present and linked through navigation.
- Confirm `_config.yml` contains the Just the Docs theme configuration.
- If local Jekyll dependencies are available, run a local build or serve command.
- If local dependencies are not available, document that verification was limited to file structure and configuration review.

## Risks and Tradeoffs

- Public GitHub Pages content should be treated as public, even if the repository setup changes later.
- Just the Docs is intentionally simple, so graph views, backlinks, and advanced digital garden behavior are out of scope.
- A notebook-first structure may become broad over time; the navigation should be kept shallow until content growth proves a need for more categories.

## Open Decisions

No open decisions remain for the first implementation plan.

Deferred decisions:

- Whether to add a custom domain after the default GitHub Pages site is working.
- Whether to add a GitHub Actions workflow if future plugins or build steps require one.
- Whether to split the learning log into dated subpages after it grows.
