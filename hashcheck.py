import hashlib
import argparse
import sqlite3
from datetime import datetime
import os
import signal
import sys
from filedate.Utils import Copy

class destination_file():
    def __init__(self, destdir):
        self.destdir = destdir
        self.sourcepath = None
        self.destpath = None
        self.destfile = None
    
    def open(self, filepath):
        self.sourcepath = filepath
        (drive, pathandfile) = os.path.splitdrive(filepath)
        (path, file)  = os.path.split(pathandfile)
        if not os.path.isdir(self.destdir + path):
            os.makedirs(self.destdir + path)
        self.destpath = self.destdir + pathandfile
        self.destfile = open(self.destpath, "wb")

    def write(self, data):
        self.destfile.write(data)

    def close(self):
        self.destfile.close()
        Copy(self.sourcepath, self.destpath).all()
        self.destfile = None

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
    parser.add_argument("--copy-to", help="Copy hashed files to destination", required=False)
    parser.add_argument("path", help="Path")

    args = parser.parse_args()

    if args.recursive and not (args.generate or args.enumerate):
        output("--recursive only available with --generate or --enumerate")
        sys.exit(1)
    
    if args.update and not args.generate:
        output("--update only available with --generate")
        sys.exit(1)

    if args.session and not args.generate:
        output("--session only available with --generate")
        sys.exit(1)

    if bool(args.db_path != None) ^ bool(args.fs_path != None):
        output("Path substitution needs both sides!")
        sys.exit(1)

    if args.path_conv_to != None:
        if args.db_path == None:
            output("Path conversion only useful with path substitution!")
            sys.exit(1)

        args.path_conv_to = args.path_conv_to.lower()
        if args.path_conv_to != "u" and args.path_conv_to !="w" :
            output("Path conversion to [w]indows or [u]nix")
            sys.exit(1)

    if args.copy_to != None:
        if not (args.generate or args.check):
            output("Copy only supported while generating or checking!")
            sys.exit(1)
        if os.path.abspath(args.path) in os.path.abspath(args.copy_to):
            output("Copy destination can't be inside the source folder!")
            sys.exit(1)

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
        if(path[-1] != os.sep):
            filter = path + os.sep + "%"
        else:
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
    if destfile:
        destfile.open(filepath)

    try:
        with open(filepath,"rb") as f: 
            file_hash = hashlib.sha256()
            chunk = f.read(1048576)
            while chunk:
                file_hash.update(chunk)
                if destfile:
                    destfile.write(chunk)
                chunk = f.read(1048576)
            f.close()
            if destfile:
                destfile.close()
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
            if outfile != None:
                outfile.flush()
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
    lastsave = datetime.now()
    crsr = mem_db.cursor()
    for row in crsr.execute("SELECT * FROM hashes WHERE filename LIKE ?", (filter,)):
        filename = row[1]
        stored_hash = row[2]

        timediff = datetime.now() - lastsave
        if timediff.total_seconds() > 300 and outfile != None:
            outfile.flush()
            lastsave = datetime.now()

        if args.verbose > 0:
            dir = os.path.dirname(filename)
            if dir != prevdir:
                prevdir = dir
                output("Processing folder {}".format(prevdir))

        output("Checking {}".format(filename), 2, 3)

        if os.path.isfile(filename):
            hash = hash_file(filename)

            if(hash != stored_hash):
                output("Hash mismatch for {}".format(filename), 0, 0)
            output("Hash OK for {}".format(filename), 2, 3)
        else:
            output("File missing: {}".format(filename), 0, 0)

def prune_db(abspath):
    filelist = getSubset(abspath, False, True)
    output("Pruning DB...")
    mem_db.execute("DELETE FROM hashes WHERE filename in ({seq})".format(seq=','.join(['?']*len(filelist))), filelist)
    mem_db.commit()

def save_db():
    if not args.test_run:
        output("Saving DB...")
        mem_db.commit()
        mem_db.backup(db)
        db.commit()

def terminate(exitcode):
    if args.generate or args.prune:
        save_db()
    db.close()
    mem_db.close()
    sys.exit(exitcode)

def exit_handler(signum, frame):
    output("Cancelled, exiting...")
    terminate(1)

if __name__ == "__main__" :
    sys.stdout.reconfigure(encoding='utf-8')
    signal.signal(signal.SIGINT, exit_handler)

    args = parse_args()

    if args.outfile:
        try:
            outfile = open(args.outfile, "w", encoding="utf-8")
        except:
            output("Unable to open output file", 0)
            sys.exit(1)
    else:
        outfile = None

    if args.copy_to != None and os.path.isdir(os.path.abspath(args.copy_to)):
        destpath = os.path.abspath(args.copy_to)
        destfile = destination_file(destpath)
    else:
        destpath = None
        destfile = None

    if args.session == None:
        args.session = 1

    mem_db = sqlite3.connect(":memory:")
    try:
        db = sqlite3.connect(args.database)
        db.execute("CREATE TABLE IF NOT EXISTS hashes(id INTEGER PRIMARY KEY, filename TEXT NOT NULL, sha256 TEXT NOT NULL, filesize INTEGER, creation_date TEXT, modified_date TEXT, timestamp TEXT, session INTEGER)")
    except sqlite3.DatabaseError:
        output("Invalid DB file")
        sys.exit(2)
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
            prune_db(abspath)
        else:
            output("Invalid path! {}".format(abspath))

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

        