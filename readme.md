# Hashcheck  

Multiplatform python-based tool for file integrity verification.  

## Basic Features

- Hash files/folders using sha256 and store the file details (path, hash, size, created/modified dates) in a SQLite database
- Verify files/folders against the stored hashes
- Update DB entries against new file state
- Find files missing from database / from filesystem
- Prune missing files from database

## Advanced Features

- Path remapping (used e.g. to generate hashes on one machine, then run the check on another machine hosting a backup where the paths are different)
- Path conversion (for above scenario, in the case of different Windows/Unix OSes)
- Copy while hashing (store hashes while making a backup copy)

## Usage

The `hashcheck.py` script on the does not implement the "Copy while hashing" feature and has no requirements other than a default install of Python >= 3.7.  
The `hashcheck_copy.py` script does, but requires the python module `filedate`. Install with `pip install filedate`.

The database being sqlite allows for easy external filtering/manipulation with tools such as [SQLite Browser](https://sqlitebrowser.org/) in case the desired filtering is not provided.

```
usage: hashcheck.py [-h] (-g | -c | -e | -m | -p) [-r] [-u] [-t] [-v] [-d DATABASE] [-o OUTFILE] [-s SESSION] [--db-path DB_PATH] [--fs-path FS_PATH] [--path-conv-to PATH_CONV_TO] [--copy-to COPY_TO] path

positional arguments:
  path                  Path

options:
  -h, --help            show this help message and exit
  -g, --generate        Generate hashes for new files in specified file/directory
  -c, --check           Check stored hashes for specified file/directory (always recursively)
  -e, --enumerate       List files not present in DB
  -m, --missing         Only check for missing files (always recursively)
  -p, --prune           Prune missing files from DB (always recursively)
  -r, --recursive       Recursive search
  -u, --update          Update existing hashes
  -t, --test-run        Test run
  -v, --verbose         verbose output (repeat for increased verbosity)
  -d DATABASE, --database DATABASE
                        Specify database file
  -o OUTFILE, --outfile OUTFILE
                        Output to file
  -s SESSION, --session SESSION
                        Session number
  --db-path DB_PATH     Path in DB
  --fs-path FS_PATH     Path in filesystem
  --path-conv-to PATH_CONV_TO
                        Convert slashes in paths to (u/w)
  --copy-to COPY_TO     Copy hashed files to destination
```

The database name can be specified using `-d` for storing separate DBs per drive, purpose,...  
An output file can be specified using `-o` which will by default contain the important events that might be missed in the console output (hash mismatch, missing file, file couldn't be opened...). Verbosity both in the console and file can be increased with `-v`, `-vv` and `-vvv`  
A session number can be specified with `-s`, it has no use other than being included in a DB column for later use.
The `-t` option will do a test run, i.e. list all operations but without modifying the database.

Typical usage examples:
- `python3 hashcheck.py -g [path]` to hash either the specified file or all files in the specified directory non-recursively
- `python3 hashcheck.py -gr [path]` to hash files in the specified directory recursively
- `python3 hashcheck.py -c [path]` to check files in the specified directory recursively against the database
- `python3 hashcheck.py -gru [path]` to re-hash files in the specified directory recursively and update the database if different
- `python3 hashcheck.py -e [path]` to enumerate new files that have not yet been hashed, supports `-r`
- `python3 hashcheck.py -m [path]` to list files missing in the specified directory recursively
- `python3 hashcheck.py -p [path]` to delete missing files in the specified directory recursively from the database
- `python3 hashcheck.py -c --db-path C:\users\user\path --fs-path /mnt/backup --path-conv-to u /mnt/backup` to check a tree originally hashed from `C:\users\user\path` on a Windows machine that is now stored in `/mnt/backup` on a linux machine

## Technical notes

The database is loaded into and operated on in RAM for performance reasons. The file on disk is treated read-only except in the generate and prune modes. In these modes it's saved to disk on normal exit, on close via `Ctrl-C` and automatically every 5 minutes during hashing.   
RAM usage will grow with the number of files in the DB, about 1GB for 1.5M files.  
Performance-wise hashing itself on large files should run up to about 400-500MB/s, on small files handling about 6000 files/min.

## TODO
- Store checks in DB
- Allow running a check on a large root but only for files not checked in the last X days
