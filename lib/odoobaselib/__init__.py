# -*- coding: utf-8 -*-
import logging
import os

from glob import glob
from pprint import pformat

import yaml

# Constants needed in scripts
CUSTOM_DIR = "/opt/odoo/custom"
SRC_DIR = os.path.join(CUSTOM_DIR, 'src')
ADDONS_YAML = os.path.join(SRC_DIR, 'addons')
if os.path.isfile('%s.yaml' % ADDONS_YAML):
    ADDONS_YAML = '%s.yaml' % ADDONS_YAML
else:
    ADDONS_YAML = '%s.yml' % ADDONS_YAML
ADDONS_DIR = "/opt/odoo/auto/addons"
CLEAN = os.environ.get("CLEAN") == "true"
AUTO_REQUIREMENTS = os.environ.get("AUTO_REQUIREMENTS") == "true"
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")
FILE_APT_BUILD = os.path.join(
    CUSTOM_DIR, 'dependencies', 'apt_build.txt',
)
PRIVATE = "private"
CORE = "odoo/addons"
PRIVATE_DIR = os.path.join(SRC_DIR, PRIVATE)
CORE_DIR = os.path.join(SRC_DIR, CORE)
ODOO_VERSION = float(os.environ["ODOO_VERSION"])
MANIFESTS = ("__manifest__.py", "__openerp__.py")
if ODOO_VERSION < 10:
    MANIFESTS = MANIFESTS[1:]

# Customize logging for build
logger = logging.getLogger("doodba")
log_handler = logging.StreamHandler()
log_formatter = logging.Formatter("%(name)s %(levelname)s: %(message)s")
log_handler.setFormatter(log_formatter)
logger.addHandler(log_handler)
_log_level = os.environ.get("LOG_LEVEL", "")
if _log_level.isdigit():
    _log_level = int(_log_level)
elif _log_level in LOG_LEVELS:
    _log_level = getattr(logging, _log_level)
else:
    if _log_level:
        logger.warning("Wrong value in $LOG_LEVEL, falling back to INFO")
    _log_level = logging.INFO
logger.setLevel(_log_level)


class AddonsConfigError(Exception):
    def __init__(self, message, *args):
        super(AddonsConfigError, self).__init__(message, *args)
        self.message = message


def addons_config(filtered=True, strict=False):
    """Yield addon name and path from ``ADDONS_YAML``.

    :param bool filtered:
        Use ``False`` to include all addon definitions. Use ``True`` (default)
        to include only those matched by ``ONLY`` clauses, if any.

    :param bool strict:
        Use ``True`` to raise an exception if any declared addon is not found.
    """
    config = dict()
    missing_glob = set()
    missing_manifest = set()
    special_missing = {PRIVATE, CORE}
    try:
        with open(ADDONS_YAML) as addons_file:
            for doc in yaml.load_all(addons_file):
                # When not filtering, private and core addons should be either
                # defined under every doc, or defaulted to `*` in the
                # ones where it is missing
                if not filtered:
                    doc.setdefault(CORE, ["*"])
                    doc.setdefault(PRIVATE, ["*"])
                # Skip sections with ONLY and that don't match
                elif any(os.environ.get(key) not in values
                         for key, values in doc.get("ONLY", dict()).items()):
                    logger.debug("Skipping section with ONLY %s", doc["ONLY"])
                    continue
                # Flatten all sections in a single dict
                for repo, addons in doc.items():
                    if repo == "ONLY":
                        continue
                    logger.debug("Processing %s repo", repo)
                    special_missing.discard(repo)
                    for partial_glob in addons:
                        logger.debug("Expanding glob %s", partial_glob)
                        full_glob = os.path.join(SRC_DIR, repo, partial_glob)
                        found = glob(full_glob)
                        if not found:
                            missing_glob.add(full_glob)
                            logger.debug(
                                "Skipping unexpandable glob '%s'",
                                full_glob)
                            continue
                        for addon in found:
                            manifests = (
                                os.path.join(addon, m) for m in MANIFESTS
                            )
                            if not any(os.path.isfile(m) for m in manifests):
                                missing_manifest.add(addon)
                                logger.debug(
                                    "Skipping '%s' as it is not a valid Odoo "
                                    "module", addon)
                                continue
                            logger.debug("Registering addon %s", addon)
                            addon = os.path.basename(addon)
                            config.setdefault(addon, set())
                            config[addon].add(repo)
    except IOError:
        logger.debug('Could not find addons configuration yaml.')
    # Fail now if running in strict mode
    if strict:
        error = []
        if missing_glob:
            error += ["Addons not found:", pformat(missing_glob)]
        if missing_manifest:
            error += ["Addons without manifest:", pformat(missing_manifest)]
        if error:
            raise AddonsConfigError(
                "\n".join(error),
                missing_glob,
                missing_manifest,
            )
    # By default, all private and core addons are enabled
    for repo in special_missing:
        logger.debug("Auto-adding all addons from %s", repo)
        for addon in glob(os.path.join(SRC_DIR, repo, "*")):
            addon = os.path.basename(addon)
            config.setdefault(addon, set())
            config[addon].add(repo)
    logger.debug("Resulting configuration: %r", config)
    for addon, repos in config.items():
        # Private addons are most important
        if PRIVATE in repos:
            yield addon, PRIVATE
            continue
        # Odoo core addons are least important
        if repos == {CORE}:
            yield addon, CORE
            continue
        repos.discard(CORE)
        # Other addons fall in between
        if len(repos) != 1:
            raise AddonsConfigError(
                u"Addon {} defined in several repos {}".format(addon, repos),
            )
        yield addon, repos.pop()
