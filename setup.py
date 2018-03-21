from setuptools import setup, find_packages

version = open('pyopenapi/VERSION', 'r').readline().strip()

setup(
    name = 'pyopenapi',
    packages = find_packages(exclude=['*.tests.*']),
    version = version,
    description = 'Library for developing backward-compatible tools on OpenAPI',
    author = 'Mission Liao',
    author_email = 'missionaryliao@gmail.com',
    url = 'https://github.com/pyopenapi/pyopenapi', # use the URL to the github repo
    download_url = 'https://github.com/pyopenapi/pyopenapi/tarball/{0}'.format(version),
    keywords = ['OpenAPI', 'REST'], # arbitrary keywords
    classifiers = [
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3.3',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Topic :: Software Development :: Libraries :: Python Modules',
    ],
    install_requires = ['six >= 1.7.2', 'pyaml>=15.03.1', 'validate_email']
)

