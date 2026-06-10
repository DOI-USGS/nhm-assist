import argparse

from assist.workspace.service import (
    bootstrap_workspace,
    copy_example_model,
    create_model,
    create_project,
    set_active_model,
    get_models,
    get_projects,
    import_model,
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

    create_model_parser = subparsers.add_parser("create-model")
    create_model_parser.add_argument("--workspace-root", required=True)
    create_model_parser.add_argument("--project-name", required=True)
    create_model_parser.add_argument("--model-name", required=True)

    list_models_parser = subparsers.add_parser("list-models")
    list_models_parser.add_argument("--workspace-root", required=True)
    list_models_parser.add_argument("--project-name", required=True)

    copy_model_parser = subparsers.add_parser("copy-example-model")
    copy_model_parser.add_argument("--workspace-root", required=True)
    copy_model_parser.add_argument("--project-name", required=True)
    copy_model_parser.add_argument("--model-name", required=True)
    copy_model_parser.add_argument("--example-name", required=True)

    import_model_parser = subparsers.add_parser("import-model")
    import_model_parser.add_argument("--workspace-root", required=True)
    import_model_parser.add_argument("--project-name", required=True)
    import_model_parser.add_argument("--model-name", required=True)
    import_model_parser.add_argument("--source-dir", required=True)

    set_active_model_parser = subparsers.add_parser("project-set-active-model")
    set_active_model_parser.add_argument("--workspace-root", required=True)
    set_active_model_parser.add_argument("--project-name", required=True)
    set_active_model_parser.add_argument("--model-name", required=True)

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
    if args.command == "create-model":
        create_model(args.workspace_root, args.project_name, args.model_name)
        return 0
    if args.command == "list-models":
        for model in get_models(args.workspace_root, args.project_name):
            print(model.name)
        return 0
    if args.command == "copy-example-model":
        copy_example_model(
            args.workspace_root,
            args.project_name,
            args.model_name,
            args.example_name,
        )
        return 0
    if args.command == "import-model":
        import_model(
            args.workspace_root,
            args.project_name,
            args.model_name,
            args.source_dir,
        )
        return 0
    if args.command == "project-set-active-model":
        set_active_model(
            args.workspace_root,
            project_name=args.project_name,
            model_name=args.model_name,
        )
        return 0

    parser.error(f"unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
