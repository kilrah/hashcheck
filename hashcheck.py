import hashlib
import argparse
import sqlite3
from datetime import datetime
import os
import signal
import sys

def parse_args():
    parser = argparse.ArgumentParser()
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument("-g", "--generate", help="Generate hashes for new files in specified file/directory", action='store_true')
    mode_group.add_argument("-c", "--check", help="Check stored hashes for specified file/directory (always recursively)", action='store_true')
    mode_group.add_argument("-e", "--enumerate", help="List files not present in DB", action='store_true')
    mode_group.add_argument("-m", "--missing", help="Only check for missing files (always recursively)", action='store_true')
    mode_group.add_argument("-p", "--prune", help="Prune missing files from DB (always recursively)", action='store_true')
    parser.add_argument("-r", "--recursive", help="Recursive search", action='store_true')
    parser.add_argument("-u", "--update", help="Update existing hashes", required=False, action='store_true')
    parser.add_argument("-t", "--test-run", help="Test run", action='store_true')
    parser.add_argument('-v', '--verbose', action='count', default=0, help="verbose output (repeat for increased verbosity)")
    parser.add_argument("-d", "--database", help="Specify database file", required=False, default="hashes.sqlite")
    parser.add_argument("-o", "--outfile", help="Output to file", required=False)
    parser.add_argument("-s", "--session", help="Session number", required=False, type=int)
    parser.add_argument("--db-path", help="Path in DB", required=False)
    parser.add_argument("--fs-path", help="Path in filesystem", required=False)
    parser.add_argument("--path-conv-to", help="Convert slashes in paths to (u/w)", required=False)
    parser.add_argument("path", help="Path")

    args = parser.parse_args()

    if args.recursive and not (args.generate or args.enumerate):
        output("--recursive only available with --generate or --enumerate")
        exit(1)
    
    if args.update and not args.generate:
        output("--update only available with --generate")
        exit(1)

    if args.session and not args.generate:
        output("--session only available with --generate")
        exit(1)

    if bool(args.db_path != None) ^ bool(args.fs_path != None):
        output("Path substitution needs both sides!")
        exit(1)

    if args.path_conv_to != None:
        if args.db_path == None:
            output("Path conversion only useful with path substitution!")
            exit(1)

        args.path_conv_to = args.path_conv_to.lower()
        if args.path_conv_to != "u" and args.path_conv_to !="w" :
            output("Path conversion to [w]indows or [u]nix")
            exit(1)

    return args

def output(string, to_stdout = 0, to_file = None):
    if args.verbose >= to_stdout:
        print(string)
    if to_file != None and args.verbose >= to_file and outfile != None:
        print(string, file=outfile)

def getFileList(path, recursive):
    output("Listing files and folders...")
    filelist = []
    if os.path.isfile(path):
        filelist = [path]
    elif os.path.isdir(path):
        for (dirpath, dirnames, filenames) in os.walk(path):
            for f in filenames:
                filelist.append(os.path.join(dirpath, f))
            if not recursive:
                break
    else:
        output("Invalid path! {}".format(path))
        terminate(2)

    return filelist

def getFilter(path):
    if os.path.isfile(path):
        filter = path
    elif os.path.isdir(path):
        filter = path + "%"
    else:
        filter = "%"

    return filter

def getSubset(abspath, new, recursive):
    filelist = getFileList(abspath, recursive)
    filter = getFilter(abspath)
    crsr = mem_db.cursor()
    crsr.execute("SELECT filename FROM hashes WHERE filename LIKE ?", (filter,))
    dbresults = crsr.fetchall()
    try:
        dblist = list(zip(*dbresults))[0]
    except IndexError:
        dblist = []

    if new:
        files = list(set(filelist) - set(dblist))
    else:
        files = list(set(dblist) - set(filelist))

    return sorted(files)

def hash_file(filepath):
    
    try:
        # Python >= 3.11 only
        """
        with open(filepath,"rb") as f:
            digest = hashlib.file_digest(f, "sha256")
            f.close()
        return digest.hexdigest()
        """
        
        # For python < 3.11
        with open(filepath,"rb") as f: 
            file_hash = hashlib.sha256()
            chunk = f.read(1048576)
            while chunk:
                file_hash.update(chunk)
                chunk = f.read(1048576)
            f.close()
        return file_hash.hexdigest()

    except (PermissionError, OSError):
        output("Unable to open file {}".format(filepath), 0, 0)

def generate_hashes(filelist, update):
    lastsave = datetime.now()
    crsr = mem_db.cursor()
    prevdir = ""
    crsr.execute("SELECT filename, sha256 FROM hashes")
    dbresults = crsr.fetchall()
    try:
        dblist = list(zip(*dbresults))[0]
    except IndexError:
        dblist = []
        
    if update:
        try:
            hashlist = list(zip(*dbresults))[1]
        except IndexError:
            hashlist = []

    for f in filelist:
        timediff = datetime.now() - lastsave
        if timediff.total_seconds() > 300:
            save_db()
            lastsave = datetime.now()

        dir = os.path.dirname(f)
        if dir != prevdir:
            prevdir = dir
            output("Processing folder {}".format(prevdir))
        
        if f not in dblist:
            if not args.test_run:
                output("Hashing {}".format(f), 1, 2)
                if os.path.isfile(f):
                    hash = hash_file(f)
                    if hash != None:
                        createdstr = datetime.fromtimestamp(os.path.getctime(f))
                        modifiedstr = datetime.fromtimestamp(os.path.getmtime(f))
                        mem_db.execute("INSERT INTO hashes VALUES (NULL, ?, ?, ?, ?, ?, ?, ?)", (f, hash, os.path.getsize(f), createdstr, modifiedstr, datetime.utcnow(), args.session))
                        mem_db.commit()
                else:
                    output("File was deleted: {}".format(f), 0, 0)
            else:
                output("Hashing skipped {}".format(f), 0, 0)

        else:
            if update:
                index = dblist.index(f)
                oldhash = hashlist[index]
                
                if os.path.isfile(f):
                    hash = hash_file(f)
                    if hash != oldhash:
                        if not args.test_run:
                            output("Updating file {}".format(f), 0, 0)
                            createdstr = datetime.fromtimestamp(os.path.getctime(f))
                            modifiedstr = datetime.fromtimestamp(os.path.getmtime(f))
                            mem_db.execute("UPDATE hashes SET sha256=?, filesize=?, creation_date=?, modified_date=?, timestamp=?, session=? WHERE filename=?", (hash, os.path.getsize(f), createdstr, modifiedstr, datetime.utcnow(), args.session, f))
                            mem_db.commit()
                        else:
                            output("Update skipped: {}".format(f), 0, 0)
                    else:
                        output("Hash already correct: {}".format(f), 1, 2)
                else:
                    output("File was deleted: {}".format(f), 0, 0)

def check_hashes(filter):
    prevdir = ""
    crsr = mem_db.cursor()
    for row in crsr.execute("SELECT * FROM hashes WHERE filename LIKE ?", (filter,)):
        filename = row[1]
        stored_hash = row[2]
        output("Checking {}".format(filename), 2, 3)

        if args.verbose > 0:
            dir = os.path.dirname(filename)
            if dir != prevdir:
                prevdir = dir
                output("Processing folder {}".format(prevdir))

        if os.path.isfile(filename):
            hash = hash_file(filename)

            if(hash != stored_hash):
                output("Hash mismatch for {}".format(filename), 0, 0)
            output("Hash OK for {}".format(filename), 2, 3)
        else:
            output("File missing: {}".format(filename), 0, 0)

def prune_db(filter):
    crsr = mem_db.cursor()
    for row in crsr.execute("SELECT * FROM hashes WHERE filename LIKE ?", (filter,)):
        filename = row[1]
        if not os.path.isfile(filename):
            if not args.test_run:
                output("Deleting file entry {}".format(filename), 0, 0)
                mem_db.execute("DELETE FROM hashes WHERE filename=?", (filename,))
                mem_db.commit()
            else:
                output("Skipped deleting entry {}".format (filename), 0, 0)

def save_db():
    if not args.test_run:
        output("Saving DB...")
        mem_db.backup(db)
        db.commit()

def terminate(exitcode):
    if args.generate or args.prune:
        save_db()
    db.close()
    mem_db.close()
    exit(exitcode)

def exit_handler(signum, frame):
    output("Cancelled, exiting...")
    terminate(1)

if __name__ == "__main__" :
    sys.stdout.reconfigure(encoding='utf-8')
    signal.signal(signal.SIGINT, exit_handler)

    args = parse_args()

    if args.outfile:
        try:
            outfile = open(args.outfile, "w")
        except:
            output("Unable to open output file", 0)
            exit(1)
    else:
        outfile = None

    if args.session == None:
        args.session = 1

    mem_db = sqlite3.connect(":memory:")
    try:
        db = sqlite3.connect(args.database)
        db.execute("CREATE TABLE IF NOT EXISTS hashes(id INTEGER PRIMARY KEY, filename TEXT NOT NULL, sha256 TEXT NOT NULL, filesize INTEGER, creation_date TEXT, modified_date TEXT, timestamp TEXT, session INTEGER)")
    except sqlite3.DatabaseError:
        output("Invalid DB file")
        exit(2)
    db.commit()
    db.backup(mem_db)

    start = datetime.now()

    if args.db_path != None and args.fs_path != None and not args.generate and not args.prune:
        mem_db.execute("UPDATE hashes SET filename = REPLACE(filename, ?, ?) WHERE filename LIKE ?", (args.db_path, args.fs_path, "%"+args.db_path+"%"))
        mem_db.commit()

        if args.path_conv_to != None:
            if args.path_conv_to == "w":
                fromChar = "/"
                toChar = "\\"
            else:
                fromChar = "\\"
                toChar = "/"
            mem_db.execute("UPDATE hashes SET filename = REPLACE(filename, ?, ?)", (fromChar, toChar))
            mem_db.commit()

    abspath = os.path.abspath(args.path)
    if args.generate:
        if not args.update:
            filelist = getSubset(abspath, True, args.recursive)
        else:
            filelist = getFileList(abspath, args.recursive)
        generate_hashes(filelist, args.update)
    
    elif args.check:
        filter = getFilter(abspath)
        check_hashes(filter)

    elif args.prune:
        if os.path.exists(abspath):
            filter = getFilter(abspath)
        else:
            # Avoid a % for an already deleted file
            filter = abspath
        
        prune_db(filter)

    elif args.enumerate or args.missing:
        if args.enumerate:    
            text = "New file:"
            new = True
        elif args.missing:
            text = "File missing:"
            new = False

        files = getSubset(abspath, new, args.recursive or args.missing)

        for f in files:
            output ("{} {}".format(text, f), 0, 0)

    output ("Time : {}".format (datetime.now()-start), 0)
    terminate(0)

        