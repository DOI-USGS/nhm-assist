import argparse

from assist.workspace.service import (
    bootstrap_workspace,
    copy_example_project,
    create_project,
    get_projects,
    import_project,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    bootstrap_parser = subparsers.add_parser("bootstrap")
    bootstrap_parser.add_argument("--workspace-root", required=True)

    create_parser = subparsers.add_parser("create-project")
    create_parser.add_argument("--workspace-root", required=True)
    create_parser.add_argument("--project-name", required=True)

    list_parser = subparsers.add_parser("list-projects")
    list_parser.add_argument("--workspace-root", required=True)

    copy_parser = subparsers.add_parser("copy-example")
    copy_parser.add_argument("--workspace-root", required=True)
    copy_parser.add_argument("--project-name", required=True)
    copy_parser.add_argument("--example-name", required=True)

    import_parser = subparsers.add_parser("import-project")
    import_parser.add_argument("--workspace-root", required=True)
    import_parser.add_argument("--project-name", required=True)
    import_parser.add_argument("--source-dir", required=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "bootstrap":
        bootstrap_workspace(args.workspace_root)
        return 0
    if args.command == "create-project":
        create_project(args.workspace_root, args.project_name)
        return 0
    if args.command == "list-projects":
        for project in get_projects(args.workspace_root):
            print(project.name)
        return 0
    if args.command == "copy-example":
        copy_example_project(args.workspace_root, args.project_name, args.example_name)
        return 0
    if args.command == "import-project":
        import_project(args.workspace_root, args.project_name, args.source_dir)
        return 0

    parser.error(f"unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
