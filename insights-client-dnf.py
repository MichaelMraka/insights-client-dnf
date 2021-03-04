
import time
import json
import resource

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

class DnfManager:
    def __init__(self):
        self.base = dnf.base.Base()
        self.releasever = dnf.rpm.detect_releasever("/")
        self.basearch = dnf.rpm.basearch(hawkey.detect_arch())
        self.packages = []
        self.repos = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    @staticmethod
    def pkg_cmp(a, b):
        if a.name != b.name:
            return -1 if a.name < b.name else 1
        vercmp = rpm.labelCompare((str(a.e), a.v, a.r), (str(b.e), b.v, b.r))
        if vercmp != 0:
            return vercmp
        if a.reponame != b.reponame:
            return -1 if a.reponame < b.reponame else 1
        return 0

    def sorted_pkgs(self, pkgs):
        # if package is installed more than once (e.g. kernel)
        # don't report other installed (i.e. with @System repo) as updates
       return sorted([pkg for pkg in pkgs if pkg.reponame != "@System"], key=cmp_to_key(self.pkg_cmp))

    def load(self):
        self.base.conf.read()
        self.base.conf.cacheonly = True
        self.base.read_all_repos()
        self.base.fill_sack(load_system_repo=True, load_available_repos=True)
        self.packages = self.base.sack.query()
        self.repos = self.base.repos

    def enabled_repos(self):
        return [repo.id for repo in self.base.repos.iter_enabled()]

    def installed_packages(self):
        return self.packages.installed().run()

    def updates(self, pkg):
        name = pkg.name
        evr = "{}:{}-{}".format(pkg.epoch, pkg.version, pkg.release)
        arch = pkg.arch
        nevra = "{}-{}.{}".format(name, evr, arch)
        updates_list = []
        for upd in self.packages.filter(name=name, arch=arch, evr__gt=evr):
            updates_list.append(upd)
        return nevra, updates_list

    @staticmethod
    def pkg_nevra(pkg):
        return "{}-{}:{}-{}.{}".format(pkg.name, pkg.epoch, pkg.version,
                                       pkg.release, pkg.arch)

    @staticmethod
    def pkg_repo(pkg):
        return pkg.reponame

    @staticmethod
    def advisory(pkg):
        errata = pkg.get_advisories(hawkey.EQ)
        return errata[0].id

    def last_update(self):
        last_ts = 0
        for repo in self.base.repos.iter_enabled():
            repo_ts = repo._repo.getTimestamp()
            if repo_ts > last_ts:
                last_ts = repo_ts
        return last_ts


class YumManager:
    def __init__(self):
        self.base = yum.YumBase()
        self.base.doGenericSetup(cache=1)
        self.releasever = self.base.conf.yumvar['releasever']
        self.basearch = self.base.conf.yumvar['basearch']
        self.packages = []
        self.repos = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    @staticmethod
    def pkg_cmp(a, b):
        vercmp = a.verCMP(b)
        if vercmp != 0:
            return vercmp
        if a.repoid != b.repoid:
            return -1 if a.repoid < b.repoid else 1
        return 0

    def sorted_pkgs(self, pkgs):
        return sorted(pkgs, key=cmp_to_key(self.pkg_cmp))

    def load(self):
        self.base.doRepoSetup()
        self.base.doSackSetup()
        self.packages = self.base.pkgSack.returnPackages()
        self.repos = self.base.repos.repos

    def enabled_repos(self):
        return [repo.id for repo in self.base.repos.listEnabled()]

    def installed_packages(self):
        return self.base.rpmdb.returnPackages()

    def updates(self, pkg):
        nevra = pkg.nevra
        updates_list = []
        for upg in self.base.pkgSack.returnPackages(patterns=[pkg.na]):
            if upg.verGT(pkg):
                updates_list.append(upg)
        return nevra, updates_list

    @staticmethod
    def pkg_nevra(pkg):
        return "{}-{}:{}-{}.{}".format(pkg.name, pkg.epoch, pkg.version,
                                       pkg.release, pkg.arch)

    @staticmethod
    def pkg_repo(pkg):
        return pkg.repoid

    def advisory(self, pkg):
        adv = self.base.upinfo.get_notice(pkg.nvr)
        if adv:
            return adv.get_metadata()['update_id']
        return None

    @staticmethod
    def last_update():
        return 0


#------- main ------------
try:
    # dnf based system
    import dnf
    import hawkey
    import rpm
    UpdatesManager = DnfManager
except ImportError:
    # yum based system
    import yum
    from yum import updateinfo
    UpdatesManager = YumManager

with UpdatesManager() as umgr:
    with Timer("Repo load"):
        umgr.load()
    if DEBUG:
        print("Loaded repos: %d" % len(umgr.repos))
        print("Loaded packages: %d " % len(umgr.packages))
        print("Memory usage: %s MB" % (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024))

    with Timer("Complete request(sum of above)"):
            response = {
                "releasever": umgr.releasever,
                "basearch": umgr.basearch,
                "repository_list": umgr.enabled_repos(),
                "update_list": {},
            }

            data = {}
            data['package_list'] = umgr.installed_packages()
            with Timer('Upgrades evaluation'):
                    updates = {}
                    for pkg in data["package_list"]:
                        (nevra, updates_list) = umgr.updates(pkg)
                        updates[nevra] = updates_list

            with Timer('Output formating'):
                    for (nevra, update_list) in updates.items():
                        if update_list:
                            out_list = []
                            for pkg in umgr.sorted_pkgs(update_list):
                                pkg_dict = {
                                    "package": umgr.pkg_nevra(pkg),
                                    "repository": umgr.pkg_repo(pkg),
                                    "basearch": response["basearch"],
                                    "releasever": response["releasever"],
                                    }
                                erratum = umgr.advisory(pkg)
                                if erratum:
                                    pkg_dict["erratum"] = erratum
                                out_list.append(pkg_dict)
                            response["update_list"][nevra] = {"available_updates": out_list}

            ts = umgr.last_update()
            if ts:
                response["metadata_time"] = time.strftime("%FT%TZ", time.gmtime(ts))
            print(json.dumps(response))
            if DEBUG:
                print("Memory usage: %s MB" % (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024))
