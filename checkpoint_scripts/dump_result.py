import argparse

from checkpoint_postprocess import dump_result


def parse_csv_ints(value):
    return [int(item) for item in value.split(",")]


def build_arg_parser():
    parser = argparse.ArgumentParser(
        description="Generate cluster metadata and checkpoint worklists",
    )
    parser.add_argument("--base-path", required=True, help="Checkpoint archive root")
    parser.add_argument(
        "--spec-apps",
        required=True,
        help="Comma-separated workload names",
    )
    parser.add_argument(
        "--times",
        default="1,1,1",
        help="Comma-separated profiling,cluster,checkpoint counts",
    )
    parser.add_argument(
        "--ids",
        default="0,0,0",
        help="Comma-separated profiling,cluster,checkpoint start ids",
    )
    return parser


def main():
    args = build_arg_parser().parse_args()
    workloads = [item for item in args.spec_apps.split(",") if item]
    dump_result(
        base_path=args.base_path,
        spec_app_list=workloads,
        times=parse_csv_ints(args.times),
        ids=parse_csv_ints(args.ids),
    )


if __name__ == "__main__":
    main()
