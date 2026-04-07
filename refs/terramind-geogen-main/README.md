# terramind-geogen

## Cloning the codebase & Python package installation

You can clone the repository as follows:


```bash
git clone https://github.com/a-banze/terramind-geogen.git
```
It is recommended to install the package in a virtual environment using python 3.11.9. You can create a virtual environment as follows:

```bash
// using conda / micromamba
micromamba create -n terramind-geogen -c conda-forge --override-channels python=3.11.14
micromamba activate terramind-geogen
```

You can then install the codebase as a python package as follows:

```bash
cd terramind-geogen
pip install .  # "pip install -e ." for development
```
