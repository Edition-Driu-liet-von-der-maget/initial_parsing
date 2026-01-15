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