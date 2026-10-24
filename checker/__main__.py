"""Entry point: python -m checker <data_pack_folder>"""

import sys
import os


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m checker <data_pack_folder>")
        print("  Reads the data pack and writes flags.csv to the current directory.")
        sys.exit(1)

    data_dir = os.path.abspath(sys.argv[1])
    if not os.path.isdir(data_dir):
        print(f"Error: '{data_dir}' is not a directory.")
        sys.exit(1)

    # ---------- load ----------
    from checker.loader import load_data_pack

    print(f"Loading data pack from: {data_dir}")
    pack = load_data_pack(data_dir)
    print(
        f"  Loaded {len(pack['data'])} station(s), "
        f"{len(pack['gps'])} GPS file(s), "
        f"{len(pack['maintenance'])} maintenance note(s)."
    )

    # ---------- run checks ----------
    from checker.checks import run_all_checks

    print("\nRunning checks ...")
    flags = run_all_checks(pack)
    print(f"  Total flags generated: {len(flags)}")

    # ---------- write output ----------
    from checker.flagwriter import write_flags

    output_path = os.path.join(os.getcwd(), "flags.csv")
    write_flags(flags, output_path)
    print(f"\nDone. Wrote {len(flags)} flags to {output_path}")


if __name__ == "__main__":
    main()
