"""Include the shared web UI in both wheel and source distributions."""
from pathlib import Path
from setuptools.command.build_py import build_py

class BuildWithWeb(build_py):
    def run(self):
        super().run()
        destination = Path(self.build_lib) / 'mypa' / 'web'
        destination.mkdir(parents=True, exist_ok=True)
        for source in (Path(__file__).parent / 'web').iterdir():
            if source.suffix in ('.html', '.js', '.css'):
                self.copy_file(str(source), str(destination / source.name))
