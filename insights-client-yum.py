#!/usr/bin/python

import time
import json
import resource

import yum
from yum import updateinfo
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
    vercmp = a.verCMP(b)
    if vercmp != 0:
        return vercmp
    if a.repoid != b.repoid:
        return -1 if a.repoid < b.repoid else 1
    return 0

def sorted_pkgs(pkgs):
       return sorted(pkgs, key=cmp_to_key(pkg_cmp) )

def get_advisory_name(base, pkg):
    adv = base.upinfo.get_notice(pkg.nvr)
    if adv:
        return adv.get_metadata()['update_id']
    return None

#-------- main ------------
base = yum.YumBase()
if base:
    with Timer("Repo load"):
        #base.read_all_repos()
        #base.fill_sack(load_system_repo=True, load_available_repos=True)
        base.doConfigSetup()
        base.doRepoSetup()
        base.doSackSetup()
    if DEBUG:
        print("Loaded repos:", len(base.repos))
        print("Loaded packages:", len(base.sack.query()))
        print("Memory usage: %s MB" % (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024))
    with Timer("Complete request(sum of above)"):
            response = {
                "releasever": base.conf.yumvar['releasever'],
                "basearch": base.conf.yumvar['basearch'],
                "repository_list": [repo.id for repo in base.repos.listEnabled()],
                "update_list": {},
            }

#            with Timer('Repo filter'):
#                repo_query = yum.YumBaseQuery()

            data = {}
            data['package_list'] = base.rpmdb.returnPackages()
            with Timer('Upgrades evaluation'):
                    updates = {}
                    for pkg in data["package_list"]:
                        #name = pkg.name
                        #evr = "{}:{}-{}".format(pkg.epoch, pkg.version, pkg.release)
                        #arch = pkg.arch
                        #nevra = "{}-{}.{}".format(pkg.name, evr, pkg.arch)
                        nevra = pkg.nevra
                        updates[nevra] = []
                        #for upg in base.pkgSack.returnPackages(patterns=["{}.{}".format(name, arch)]):
                        for upg in base.pkgSack.returnPackages(patterns=[pkg.na]):
                            if upg.verGT(pkg):
                                updates[nevra].append(upg)

            with Timer('Output formating'):
                    for (nevra, update_list) in updates.items():
                        if update_list:
                            out_list = []
                            for pkg in sorted_pkgs(update_list):
                                pkg_dict = {
                                    "package": "{}-{}:{}-{}.{}".format(pkg.name, pkg.epoch, pkg.version,
                                                                    pkg.release, pkg.arch),
                                    "repository": pkg.repoid,
                                    "basearch": response["basearch"],
                                    "releasever": response["releasever"],
                                    }
                                errata = get_advisory_name(base, pkg)
                                if errata:
                                    pkg_dict["erratum"] = errata
                                out_list.append(pkg_dict)
                            response["update_list"][nevra] = {"available_updates": out_list}

            print(json.dumps(response))
            if DEBUG:
                print("Memory usage: %s MB" % (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024))
