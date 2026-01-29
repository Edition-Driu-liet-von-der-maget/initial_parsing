from pathlib import Path
import pandas as pd

def clear_tei_folder(outdir: str):
    out_dir_resolved = resolve_path_relative_to_script(outdir)
    for file in out_dir_resolved.glob("*.xml"):
        file.unlink()

def resolve_path_relative_to_script(file_path: str) -> Path:
    # check if path is absolute
    if Path(file_path).is_absolute():
        return Path(file_path)
    # else resolve relative to this script's directory
    script_dir = Path(__file__).resolve().parent
    return script_dir / file_path

def excel_to_csv(file_path: str):
    abs_file_path: Path = resolve_path_relative_to_script(file_path)
    df = pd.read_excel(abs_file_path, header=0) #, sheetname='<your sheet>'
    csv_file_path = abs_file_path.with_suffix('.csv')
    df.to_csv(csv_file_path, index=False, quotechar="'")
    return csv_file_path

def user_interaction_loop():
    import sys
    import select

    nl3 = '\n' * 3
    hash80 = '#' * 80
    print(f"{nl3}{hash80}{nl3}\nAttention, this will delete all files in the TEI output folder before processing!{nl3}{hash80}")
    sleep_countdown = 5
    print("Press Enter to start immediately, or type anything and press Enter to abort.")

    for i in range(sleep_countdown, 0, -1):
        print(f"Continuing in {i} seconds... (press Enter to continue, any other input to abort)")
        # Wait up to 1 second for user input
        rlist, _, _ = select.select([sys.stdin], [], [], 1)
        if rlist:
            line = sys.stdin.readline()
            if line.strip() == "":
                # Empty line: user pressed Enter only -> skip countdown
                break
            else:
                print("Aborted by user input.")
                sys.exit(0)

