from setuptools import setup, find_packages
setup(
    name = 'pyopenapi',
    packages = find_packages(exclude=['*.tests.*']),
    version = '0.0.2',
    description = 'A type safe Swagger Client',
    author = 'Mission Liao',
    author_email = 'missionaryliao@gmail.com',
    url = 'https://github.com/AntXlab/pyopenapi', # use the URL to the github repo
    download_url = 'https://github.com/AntXlab/pyopenapi/tarball/0.0.1', # I'll explain this in a second
    keywords = ['swagger', 'REST'], # arbitrary keywords
    classifiers = [
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 2.6',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3.3',
        'Programming Language :: Python :: 3.4',
        'Topic :: Software Development :: Libraries :: Python Modules',
    ],
    install_requires = ['six >= 1.7.2']
)

