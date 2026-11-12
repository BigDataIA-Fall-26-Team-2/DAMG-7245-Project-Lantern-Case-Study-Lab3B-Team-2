from setuptools import setup, find_packages

setup(name="lantern-cs3b", version="0.1.0",
      packages=find_packages("src") + find_packages(".", include=["services", "services.*"]),
      package_dir={"creditwatch": "src/creditwatch"},
      entry_points={"console_scripts": ["lantern=services.evaluation.cli:main"]})
