from importlib.resources import files
from pathlib import Path
from shutil import copytree


def install_example_projects(workspace):
    """Instala exemplos ausentes sem modificar projetos existentes."""
    workspace = Path(workspace).expanduser()
    projects = workspace / "projects"

    source = files("cisei_scenario_sdk").joinpath(
        "resources", "examples", "copel_palmeira"
    )
    destination = projects / "copel_palmeira"

    if destination.exists() or destination.is_symlink():
        return destination

    if not source.is_dir():
        raise FileNotFoundError(
            "Projeto de exemplo copel_palmeira não encontrado no SDK."
        )

    projects.mkdir(parents=True, exist_ok=True)

    copytree(source, destination)

    return destination
