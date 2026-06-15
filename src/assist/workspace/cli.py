import argparse

from assist.workspace.setup import run_setup
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

    subparsers.add_parser("setup")

    workspace_init_parser = subparsers.add_parser("workspace-init")
    workspace_init_parser.add_argument("--workspace-root", required=True)

    project_create_parser = subparsers.add_parser("project-create")
    project_create_parser.add_argument("--workspace-root", required=True)
    project_create_parser.add_argument("--project-name", required=True)

    project_list_parser = subparsers.add_parser("project-list")
    project_list_parser.add_argument("--workspace-root", required=True)

    model_create_parser = subparsers.add_parser("model-create")
    model_create_parser.add_argument("--workspace-root", required=True)
    model_create_parser.add_argument("--project-name", required=True)
    model_create_parser.add_argument("--model-name", required=True)

    model_list_parser = subparsers.add_parser("model-list")
    model_list_parser.add_argument("--workspace-root", required=True)
    model_list_parser.add_argument("--project-name", required=True)

    model_copy_example_parser = subparsers.add_parser("model-copy-example")
    model_copy_example_parser.add_argument("--workspace-root", required=True)
    model_copy_example_parser.add_argument("--project-name", required=True)
    model_copy_example_parser.add_argument("--model-name", required=True)
    model_copy_example_parser.add_argument("--example-name", required=True)

    model_import_parser = subparsers.add_parser("model-import")
    model_import_parser.add_argument("--workspace-root", required=True)
    model_import_parser.add_argument("--project-name", required=True)
    model_import_parser.add_argument("--model-name", required=True)
    model_import_parser.add_argument("--source-dir", required=True)

    set_active_model_parser = subparsers.add_parser("project-set-active-model")
    set_active_model_parser.add_argument("--workspace-root", required=True)
    set_active_model_parser.add_argument("--project-name", required=True)
    set_active_model_parser.add_argument("--model-name", required=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "setup":
        return run_setup()
    if args.command == "workspace-init":
        bootstrap_workspace(args.workspace_root)
        return 0
    if args.command == "project-create":
        create_project(args.workspace_root, args.project_name)
        return 0
    if args.command == "project-list":
        for project in get_projects(args.workspace_root):
            print(project.name)
        return 0
    if args.command == "model-create":
        create_model(args.workspace_root, args.project_name, args.model_name)
        return 0
    if args.command == "model-list":
        for model in get_models(args.workspace_root, args.project_name):
            print(model.name)
        return 0
    if args.command == "model-copy-example":
        copy_example_model(
            args.workspace_root,
            args.project_name,
            args.model_name,
            args.example_name,
        )
        return 0
    if args.command == "model-import":
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
