#!/usr/libexec/platform-python

import time
import json
import resource

import dnf
import hawkey
import rpm
from functools import cmp_to_key

DEBUG=False

class Timer(object):
    def __init__(self, msg=""):
        self.msg = msg
        self.start = 0

    def __enter__(self):
        self.start = time.time()
        return self

    def __exit__(self, *args):
        end = time.time()
        secs = end - self.start
        msecs = secs * 1000  # millisecs
        if DEBUG:
            print('{}: elapsed time: {} ms'.format(self.msg, msecs))

def pkg_cmp(a, b):
    if a.name != b.name:
        return -1 if a.name < b.name else 1
    vercmp = rpm.labelCompare((str(a.e), a.v, a.r), (str(b.e), b.v, b.r))
    if vercmp != 0:
        return vercmp
    if a.reponame != b.reponame:
        return -1 if a.reponame < b.reponame else 1
    return 0

def sorted_pkgs(pkgs):
       return sorted(pkgs, key=cmp_to_key(pkg_cmp) )

#-------- main ------------
with dnf.base.Base() as base:
    with Timer("Repo load"):
        base.read_all_repos()
        base.fill_sack(load_system_repo=True, load_available_repos=True)
    if DEBUG:
        print("Loaded repos:", len(base.repos))
        print("Loaded packages:", len(base.sack.query()))
        print("Memory usage: %s MB" % (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024))

    with Timer("Complete request(sum of above)"):
            response = {
                "releasever": dnf.rpm.detect_releasever("/"),
                "basearch": dnf.rpm.basearch(hawkey.detect_arch()),
                "repository_list": [repo.id for repo in base.repos.iter_enabled()],
                "update_list": {},
            }

            with Timer('Repo filter'):
                repo_query = base.sack.query()

            data = {}
            data['package_list'] = repo_query.installed().run()
            with Timer('Upgrades evaluation'):
                    updates = {}
                    for pkg in data["package_list"]:
                        name = pkg.name
                        evr = "{}:{}-{}".format(pkg.epoch, pkg.version, pkg.release)
                        arch = pkg.arch
                        nevra = "{}-{}.{}".format(pkg.name, evr, pkg.arch)
                        updates[nevra] = []
                        for pkg in repo_query.filter(name=name, arch=arch, evr__gt=evr):
                            updates[nevra].append(pkg)

            with Timer('Output formating'):
                    for (nevra, update_list) in updates.items():
                        if update_list:
                            out_list = []
                            for pkg in sorted_pkgs(update_list):
                                if pkg.reponame == "@System":
                                    # if package is installed more than once (e.g. kernel)
                                    # don't report other installed versions as updates
                                    continue
                                pkg_dict = {
                                    "package": "{}-{}:{}-{}.{}".format(pkg.name, pkg.epoch, pkg.version,
                                                                    pkg.release, pkg.arch),
                                    "repository": pkg.reponame,
                                    "basearch": response["basearch"],
                                    "releasever": response["releasever"],
                                    }
                                errata = pkg.get_advisories(hawkey.EQ)
                                if errata:
                                    pkg_dict["erratum"] = errata[0].id
                                out_list.append(pkg_dict)
                            response["update_list"][nevra] = {"available_updates": out_list}

            print(json.dumps(response))
            if DEBUG:
                print("Memory usage: %s MB" % (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024))
