#!/usr/bin/env python

import codecs
import ConfigParser
import fnmatch
import glob
import git
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
import urllib
import urllib2

#---------------------------------------------------------------------------
# Module global variables
class ModuleGlobals(object): pass
__m = ModuleGlobals()
__m.persistent_cache_enabled = False
__m.persistent_cache = {}
__m.cache = {}

#---------------------------------------------------------------------------
def setCacheEntry(key, value):
    __m.cache[key] = value
    return value

#---------------------------------------------------------------------------
def cacheEntry(key):
    return __m.cache[key]

#---------------------------------------------------------------------------
def clearCache():
    __m.cache = {}

#---------------------------------------------------------------------------
def persistentCacheEnabled():
    return __m.persistent_cache_enabled

#---------------------------------------------------------------------------
def setPersistentCacheEnabled(value):
    __m.persistent_cache_enabled = value

#---------------------------------------------------------------------------
def persistentCacheEntry(key):
    if persistentCacheEnabled():
        return __m.persistent_cache[key]
    else:
        raise KeyError

#---------------------------------------------------------------------------
def setPersistentCacheEntry(key, value):
    __m.persistent_cache[key] = value
    savePersistentCache()
    return value

#---------------------------------------------------------------------------
def clearPersistentCache():
    __m.cache = {}

#---------------------------------------------------------------------------
def getPersistentCacheFilePath():
    return os.path.join(tempfile.gettempdir(), os.path.basename(os.path.splitext(__file__)[0])+"-cache")

#---------------------------------------------------------------------------
def savePersistentCache():
    with open(getPersistentCacheFilePath(), 'w') as fileContents:
        fileContents.write(json.dumps(__m.persistent_cache, sort_keys=True, indent=4))

#---------------------------------------------------------------------------
def loadPersistentCache():
    setPersistentCacheEnabled(True)
    if not os.path.exists(getPersistentCacheFilePath()):
        return
    with open(getPersistentCacheFilePath()) as fileContents:
        __m.persistent_cache = json.load(fileContents)

#---------------------------------------------------------------------------
def connectToSlicerWiki(username='UpdateBot', password=None):
    """
    :param username:
      Username to login to Slicer wiki. The user should be granted right to use the wiki API.
    :type username:
      :class:`basestring`
    :param password:
      Password to login to Slicer wiki.
    :type username:
      :class:`basestring`

    :returns: Site object allowing to interact with the wiki.
    :rtype: :class:`mwclient.Site <mwclient:mwclient.client.Site>`
    """
    return connectToWiki(username, password, 'slicer.org', '/slicerWiki/')

#---------------------------------------------------------------------------
def connectToWikiByName(name):
    try:
        wiki = cacheEntry('wiki-{0}'.format(name))
    except KeyError:
        username = cacheEntry("wiki-{0}-username".format(name))
        password = cacheEntry("wiki-{0}-password".format(name))
        host = cacheEntry("wiki-{0}-host".format(name))
        path = cacheEntry("wiki-{0}-path".format(name))
        wiki = setCacheEntry('wiki-{0}'.format(name),
            connectToWiki(username, password, host, path))
    return wiki

#---------------------------------------------------------------------------
def connectToWiki(username, password, host, path):
    """
    :returns: Site object allowing to interact with the wiki.
    :rtype: :class:`mwclient.Site <mwclient:mwclient.client.Site>`
    """
    import mwclient

    site = mwclient.Site(host, path=path)
    site.login(username, password)

    print("\nConnected to '{host}{path}' as user '{username}'".format(
        host=site.host, path=site.path, username=username))

    return site

#---------------------------------------------------------------------------
def convertTitleToWikiAnchor(title):
    """Convert section title into a identifier that can be used to reference
    the section in link.

    :param title:
      Section title
    :type title:
      :class:`basestring`

    :returns: Anchor that can be used to reference the associated section.
    :rtype: :class:`basestring`
    """
    # Following snippet has been adapted from mediawiki code base
    # 1) normalize
    title = re.sub(r'[ _]+', ' ', title)
    # 2) See Title::newFromText in mediawiki
    title = title.replace(' ', '_')
    #   * decodeCharReferencesAndNormalize: Convert things like &eacute; &#257; or &#x3017; into normalized text
    # XXX title = decodeCharReferencesAndNormalize(title)
    #   * Strip Unicode bidi override characters.
    title = re.sub(r'\xE2\x80[\x8E\x8F\xAA-\xAE]', '', title)
    #   * Clean up whitespace
    # XXX title = re.sub(r'[ _\xA0\x{1680}\x{180E}\x{2000}-\x{200A}\x{2028}\x{2029}\x{202F}\x{205F}\x{3000}]', '_', title)
    title = title.strip('_')
    # 2) See Title::getFragmentForURL -> Title::escapeFragmentForURL -> Sanitized::escapeId
    title = re.sub(r'[ \t\n\r\f_\'"&#%]', '_', title)
    title = title.strip('_')
    title = urllib.quote_plus(title)
    #   * HTML4-style escaping
    title = title.replace('%3A', ':')
    title = title.replace('%', '.')
    return '#' + title

#---------------------------------------------------------------------------
def extractExtensionName(descriptionFile):
    return os.path.basename(os.path.splitext(descriptionFile)[0])

#---------------------------------------------------------------------------
def prettify(name):
    """Source: http://stackoverflow.com/questions/5020906/python-convert-camel-case-to-space-delimited-using-regex-and-taking-acronyms-in
    """
    name = re.sub(r'^Slicer(Extension)?[\-\_]', "", name)
    return re.sub("([a-z])([A-Z])","\g<1> \g<2>", name).replace('_', ' ')

#---------------------------------------------------------------------------
def getDescriptionFiles(extensionsIndexDir, skip = []):
    s4extFiles = []
    files = os.listdir(extensionsIndexDir)
    for descriptionFile in files:
        if not fnmatch.fnmatch(descriptionFile, '*.s4ext'):
            continue
        if extractExtensionName(descriptionFile) in skip:
            continue
        s4extFiles.append(os.path.join(extensionsIndexDir, descriptionFile))
    return s4extFiles

#---------------------------------------------------------------------------
def getExtensionHomepages(files):
    import SlicerWizard as sw

    print("\nCollecting extension homepage links")

    homepages = {}
    for file_ in files:
        desc = sw.ExtensionDescription(filepath=file_)
        name = extractExtensionName(file_)
        homepages[name] = desc.homepage
    return homepages

#---------------------------------------------------------------------------
def wikiPageExists(wikiName, page):
    try:
        exist = persistentCacheEntry(page)
    except KeyError:
        wiki = connectToWikiByName(wikiName)
        exist  = setPersistentCacheEntry(page, wiki.Pages[page].exists)
    return exist

#---------------------------------------------------------------------------
WIKI_LINK_INTERNAL = 0
WIKI_LINK_EXTERNAL = 1
WIKI_LINK_OFF = 2

#---------------------------------------------------------------------------
def wikiPageToWikiLink(page, name=None):
    if not name:
        return "[[{}]]".format(page)
    else:
        return wikiPageToWikiLink("{0}|{1}".format(page, name))

#---------------------------------------------------------------------------
def urlToWikiLink(url, name):
    return "[{0} {1}]".format(url, name)

#---------------------------------------------------------------------------
def _generateWikiLink(type_, what, name, linkName, url=None):
    if type_ == WIKI_LINK_INTERNAL:
        page = "Documentation/Nightly/{what}/{name}".format(what=what, name=name)
        return wikiPageToWikiLink(page, linkName)
    elif type_ == WIKI_LINK_EXTERNAL:
        return  urlToWikiLink(url, linkName)
    else: # WIKI_LINK_OFF
        return linkName

#---------------------------------------------------------------------------
def _createLinkItem(type_, what, name, linkName, url=None):
    return {'name' : name,
            'wikilink' : _generateWikiLink(type_, what, name, linkName, url=url),
            'type' : type_,
            'url' : url}

#---------------------------------------------------------------------------
def generateItemWikiLinks(what, wikiName, homepages):

    print("\nGenerating {0} wiki links:".format(what))

    wikiLinks = {}
    for idx, (name, homepage) in enumerate(homepages.iteritems()):
        if idx % 5 == 0:
            print("  {:.0%}".format(float(idx) / len(homepages)))

        item = _createLinkItem(WIKI_LINK_INTERNAL, what, name, prettify(name))

        # If wiki page does NOT exist use the homepage link provided in the description file
        if not wikiPageExists(wikiName, "Documentation/Nightly/{0}/{1}".format(what, name)):
            if homepage:
                item = _createLinkItem(WIKI_LINK_EXTERNAL, what, name, prettify(name), homepage)
            else:
                item = _createLinkItem(WIKI_LINK_OFF, what, name, prettify(name))

        wikiLinks[name] = item

    return wikiLinks

#---------------------------------------------------------------------------
def saveWikiPage(wikiName, name, summary, content):
    wiki = connectToWikiByName(wikiName)
    page = wiki.Pages[name]
    return page.save(content, summary=summary)

#---------------------------------------------------------------------------
def getCategoriesWithSubCategories(itemCategories):

    #----------------------------------------------------------------------
    def _getParentCategory(category):
        subModuleCategories = category.split('.')
        parentCategory = subcategories
        for subModuleCategory in subModuleCategories:
            if subModuleCategory not in parentCategory:
                parentCategory[subModuleCategory] = {}
                parentCategory[subModuleCategory]['_ITEMS_'] = []
            parentCategory = parentCategory[subModuleCategory]
        return parentCategory

    subcategories = {}
    for name in itemCategories:
        categories = ['Uncategorized']
        if len(itemCategories[name]) > 0:
            categories = itemCategories[name]

        for category in categories:
            # Skip empty category
            if not category.strip():
                continue
            # Consider sub-categories
            parentCategory = _getParentCategory(category)
            parentCategory['_ITEMS_'].append(name)

    return subcategories

#---------------------------------------------------------------------------
def getModuleCategories(modulesMetadata):
    print("\nCollecting module 'categories'")
    return {name: modulesMetadata[name]['categories'] for name in modulesMetadata}

#---------------------------------------------------------------------------
def getExtensionCategories(files):
    import SlicerWizard as sw

    print("\nCollecting extension 'categories'")
    categories = {}
    for file_ in files:
        desc = sw.ExtensionDescription(filepath=file_)
        name = extractExtensionName(file_)

        categories[name] = []
        if hasattr(desc, 'category') and desc.category.strip():
            categories[name] = [desc.category]

    return categories

#---------------------------------------------------------------------------
def _appendToDictValue(dict_, key, value, allowDuplicate=True):
    if key not in dict_:
        dict_[key] = []
    append = True
    if not allowDuplicate and value in dict_[key]:
        append = False
    if append:
        dict_[key].append(value)

#---------------------------------------------------------------------------
def parseContributors(name, contributors):
    # XXX This has been copied from [1]
    #     [1] https://github.com/Slicer/Slicer/blob/a8a01aa29210f938eaf48bb5c991681c3c67632d/Modules/Scripted/ExtensionWizard/ExtensionWizardLib/EditExtensionMetadataDialog.py#L101

    def _parseIndividuals(individuals):
        return individuals.split(",")

    def _parseOrganization(organization):
        try:
            c = organization
            c = c.strip()
            n = c.index("(")

            individuals = _parseIndividuals(c[:n].strip())
            organization = c[n+1:-1].strip()

        except ValueError:
            individuals = _parseIndividuals(organization)
            organization = ""

        return (organization, individuals)

    def _parseContributors(contributors):
        orgs = re.split("(?<=[)])\s*,", contributors)
        for c in orgs:
            c = c.strip()
            if not c:
                print("  {0}: no contributors".format(name))
                continue
            (organization, individuals) = _parseOrganization(c)
            for individual in individuals:
                if individual == "":
                    print("  {0}: organization {1} has no individuals".format(name, organization))
                    continue
                _appendToDictValue(orgToIndividuals, organization, individual)
                _appendToDictValue(individualToOrgs, individual, organization)

    orgToIndividuals = {}
    individualToOrgs = {}

    # Split by organization
    if isinstance(contributors, basestring):
        contributors = [contributors]
    for contributor in contributors:
        _parseContributors(contributor)

    return (orgToIndividuals, individualToOrgs)

#---------------------------------------------------------------------------
def getExtensionContributors(files):
    import SlicerWizard as sw
    print("\nCollecting extension 'contributors'")
    contributors = {}
    for file_ in files:
        desc = sw.ExtensionDescription(filepath=file_)
        name = extractExtensionName(file_)
        if not hasattr(desc, 'contributors'):
            print("  skipping %s: missing contributors field" % name)
            continue
        contributors[name] = desc.contributors
    return contributors

#---------------------------------------------------------------------------
def getModuleContributors(modulesMetadata):
    print("\nCollecting module 'contributors'")
    return {name: modulesMetadata[name]['contributors'] for name in modulesMetadata}

#---------------------------------------------------------------------------
def getContributingOrganizationsAndIndividuals(contributorsByItem):

    organizations = {}
    individuals = {}
    itemToOrganizations = {}
    individualToOrganizations = {}
    for name, contributors in contributorsByItem.iteritems():

        (orgToIndividuals, individualToOrgs) = parseContributors(name, contributors)

        for organization in orgToIndividuals.keys():
            _appendToDictValue(organizations, organization, name)

            itemToOrganizations[name] = orgToIndividuals

        for individual in individualToOrgs.keys():
            _appendToDictValue(individuals, individual, name)
            orgs = individualToOrgs[individual]
            for org in orgs:
                if org:
                    _appendToDictValue(individualToOrganizations, individual, org, allowDuplicate=False)

    return (organizations, individuals, itemToOrganizations, individualToOrganizations)

#---------------------------------------------------------------------------
def sortKeys(dict_, prettifyKey=False):
    """Return list of sorted dictionnary keys.
    """
    def _updateKey(s):
        s = s.lower()
        if prettifyKey:
            s = prettify(s)
        return s
    return sorted(dict_, key=_updateKey)

#---------------------------------------------------------------------------
def sortPrettifiedKeys(dict_):
    """Return list of sorted dictionnary keys.
    """
    return sortKeys(dict_, prettifyKey=True)

#---------------------------------------------------------------------------
def generateContributorsWikiLinks(extensionName, organizations):
    for org in sortPrettifiedKeys(organizations):
        orgLink = "[[#{}|{}]]".format(org, org)
        for individual in sortPrettifiedKeys(organizations[org]):
            individualLink = "[[#{}|{}]]".format(individual, individual)

#---------------------------------------------------------------------------
def tocEntryAsWikiListItem(name, level=0):
    extras = []

    individualToOrganizations = cacheEntry("individualToOrganizations")

    return linkAsWikiListItem(wikiPageToWikiLink(convertTitleToWikiAnchor(name), prettify(name)), level, extras)

#---------------------------------------------------------------------------
def individualEntryAsWikiListItem(name, level=0):
    return tocEntryAsWikiListItem(name, level)

#---------------------------------------------------------------------------
def headerForWikiList(title, teaser):
    lines = []
    lines.append(u"= {} =".format(title))
    lines.extend(teaser)
    return lines

#---------------------------------------------------------------------------
def linkAsWikiListItem(link, level=0, extras=[]):
    wikilink = link
    if isinstance(link, dict):
        wikilink = link['wikilink']
    extraTxt = "    <small>({})</small>".format(", ".join(extras)) if extras else ""
    return "{0} {1}{2}".format("*"*(level+1), wikilink, extraTxt)

#---------------------------------------------------------------------------
def footerForWikiList(title, teaser):
    return []

#---------------------------------------------------------------------------
def moduleLinkAsListItem(link, level=0):
    name = link['name']
    extras = []
    modules = cacheEntry("modules")
    if name in modules:
        extensionName = modules[name]['extensionName']
        extensionLinks = cacheEntry("extensionLinks")
        # type (cli, loadable, scripted)
        extras.append(modules[name]['moduleType'])
        # provenance (built-in or extension)
        if extensionName in extensionLinks:
            extras.append("bundled in {} extension".format(extensionLinks[extensionName]['wikilink']))
        elif extensionName == 'builtin':
            extras.append("built-in")
    return linkAsWikiListItem(link, level, extras)

#---------------------------------------------------------------------------
linksAsWikiList = (headerForWikiList, linkAsWikiListItem, headerForWikiList)

# #---------------------------------------------------------------------------
# def headerForWikiTable():
#     pass
#
# #---------------------------------------------------------------------------
# def linkAsWikiTableEntry():
#     pass
#
# #---------------------------------------------------------------------------
# def headerForWikiTable():
#     pass

#---------------------------------------------------------------------------
# linksAsWikiTable = (headerForWikiTable, linkAsWikiTableEntry, headerForWikiTable)

#---------------------------------------------------------------------------
def itemByCategoryToWiki(what, links, categories, linksRenderer=linksAsWikiList,
                         tocEntryRenderer=tocEntryAsWikiListItem, withToc=False):

    def _traverse(categories, lines, categoryCallback,
                  itemCallback=None, category=None, level=-1):
        if category:
            lines.append(categoryCallback(category, level))
        if itemCallback and '_ITEMS_' in categories:
            for item in categories['_ITEMS_']:
                lines.append(itemCallback(item))
        for subcategory in sortKeys(categories):
            if subcategory == '_ITEMS_':
                continue
            level = level + 1
            _traverse(categories[subcategory], lines, categoryCallback,
                      itemCallback=itemCallback,
                      category=subcategory,
                      level=level)
            level = level - 1

    title = "{0} by category".format(what)
    print("\nGenerating '%s' section" % title)
    teaser = []
    if withToc:
        teaser.append("{} categories:".format(len(categories)))
        _traverse(categories, teaser, tocEntryRenderer)
    else:
        teaser.append("{} categories".format(len(categories)))
    lines = []
    lines.extend(headerForWikiList(title, teaser))
    # content
    _traverse(categories, lines,
              lambda category, level: u"{0} {1} {0}".format("="*(level+2), category),
              itemCallback=linkAsWikiListItem)

    return (title, convertTitleToWikiAnchor(title), lines)

#---------------------------------------------------------------------------
def itemByNameToWiki(what, links, linksRenderer=linksAsWikiList):
    title = "{0} by name".format(what)
    print("\nGenerating '{0}' section".format(title))
    teaser = ["{0} {1}:".format(len(links), what.lower())]
    lines = []
    lines.extend(linksRenderer[0](title, teaser))
    for name in sortPrettifiedKeys(links):
        lines.append(linksRenderer[1](links[name]))
    lines.extend(linksRenderer[2](title, teaser))
    return (title, convertTitleToWikiAnchor(title), lines)

#---------------------------------------------------------------------------
def itemByPropertyToWiki(what, links, description, items,
                         linksRenderer=linksAsWikiList,
                         tocEntryRenderer=tocEntryAsWikiListItem, withToc=False):
    title = "{0} by {1}".format(what, description)
    print("\nGenerating '%s' section" % title)
    teaser = []
    if withToc:
        teaser.append("{0} {1}s:".format(len(items), description))
        for name in sortKeys(items):
            if not name:
                continue
            teaser.append(tocEntryRenderer(name))
    else:
        teaser.append("{0} {1}s".format(len(items), description))
    lines = []
    lines.extend(linksRenderer[0](title, teaser))
    for item in sortKeys(items):
        if item != "":
            lines.append("== {} ==".format(item))
        for name in sortPrettifiedKeys(items[item]):
            if item == "":
                print(u"  skipping {0}: missing '{1}'".format(name, description))
                continue
            lines.append(linksRenderer[1](links[name]))
    lines.extend(linksRenderer[2](title, teaser))
    return (title, convertTitleToWikiAnchor(title), lines)

#---------------------------------------------------------------------------
def getMetadataFiles(prefix):
    """Return a list of files associated with ``prefix``.
    """
    return glob.glob(os.path.join(getPackagesMetadataDataDirectory(), '{0}_*.json'.format(prefix)))

#---------------------------------------------------------------------------
def _merge(a, b, path=None):
    "Merge b into a"
    # See http://stackoverflow.com/a/7205107/1539918
    if path is None: path = []
    for key in b:
        if key in a:
            if isinstance(a[key], dict) and isinstance(b[key], dict):
                _merge(a[key], b[key], path + [str(key)])
            elif isinstance(a[key], list) and isinstance(b[key], list):
                a[key] = list(set(a[key] + b[key]))
            elif a[key] == b[key]:
                pass # same leaf value
            else:
                raise Exception('Conflict at %s' % '.'.join(path + [str(key)]))
        else:
            a[key] = b[key]
    return a

#---------------------------------------------------------------------------
def mergeMetadataFiles(prefix):
    """Return a merged dictonnary of all metadata files associated with ``prefix``.
    """
    #-----------------------------------------------------------------------
    def _readJson(filePath):
        with codecs.open(filePath, 'r', 'utf-8') as fileContents:
            return json.load(fileContents)
    return reduce(_merge, [_readJson(filePath) for filePath in getMetadataFiles(prefix)])

#---------------------------------------------------------------------------
def cloneRepository(git_url, repo_dir):
    """Clone ``git_url`` into ``repo_dir``.
    If a clone already exists, it returns a reference to it.
    """
    if not os.path.isdir(repo_dir):
        git.Repo.clone_from(git_url, repo_dir)
        print("Cloned '{0}' into '{1}'".format(git_url, repo_dir))

    repo = git.Repo(repo_dir)
    print("\nFound '{0}' in '{1}'".format(git_url, repo_dir))

    # Get latest change
    repo.git.pull()

    return repo

#---------------------------------------------------------------------------
SLICER_PACKAGES_METADATA_GIT_URL = 'git@github.com:Slicer/slicer-packages-metadata'
SLICER_EXTENSIONS_INDEX_GIT_URL = 'git://github.com/Slicer/ExtensionsIndex'

#---------------------------------------------------------------------------
def getPackagesMetadataTopLevelDirectory():
    return os.path.join(tempfile.gettempdir(), 'slicer-packages-metadata')

#---------------------------------------------------------------------------
def getPackagesMetadataDataDirectory():
    metadataDir = os.path.join(getPackagesMetadataTopLevelDirectory(), 'metadata')
    if not os.path.exists(metadataDir):
        os.makedirs(metadataDir)
    return metadataDir

#---------------------------------------------------------------------------
def getExtensionsIndexTopLevelDirectory():
    return os.path.join(tempfile.gettempdir(), 'slicer-extensions-index')

#---------------------------------------------------------------------------
def getModulesMetadata(wikiName):
    # Clone repository hosting package metadata
    cloneRepository(SLICER_PACKAGES_METADATA_GIT_URL, getPackagesMetadataTopLevelDirectory())

    modulesMetadata = mergeMetadataFiles('slicer-modules-metadata')

    # Collect wiki links
    links = \
        generateItemWikiLinks('Modules', wikiName, {name:"" for name in modulesMetadata.keys()})

    # Collect categories
    print("\nCollecting module 'categories with sub-categories'")
    categories = getModuleCategories(modulesMetadata)
    categoriesWithSub = getCategoriesWithSubCategories(categories)

    # Collect contributing organizations and individuals
    contributors = getModuleContributors(modulesMetadata)
    print("\nCollecting module 'contributing organizations and individuals'")
    (organizations, individuals, modulesToOrganizations, individualToOrganizations) = \
            getContributingOrganizationsAndIndividuals(contributors)

    return (links, categories, categoriesWithSub, organizations, individuals, individualToOrganizations)

#---------------------------------------------------------------------------
def getExtensionsMetadata(slicerVersion, wikiName):

    SLICER_EXTENSIONS_SKIP = ['boost', 'Eigen']

    # Clone extensions index
    repo = cloneRepository(SLICER_EXTENSIONS_INDEX_GIT_URL, getExtensionsIndexTopLevelDirectory())
    if slicerVersion not in repo.heads:
        repo.git.checkout('origin/{0}'.format(slicerVersion), b=slicerVersion)

    # Get latest change
    repo.git.pull()

    # Collect description files
    files = getDescriptionFiles(getExtensionsIndexTopLevelDirectory(), SLICER_EXTENSIONS_SKIP)

    # Collect wiki links
    links = generateItemWikiLinks('Extensions', wikiName, getExtensionHomepages(files))

    # Collect categories
    print("\nCollecting module 'categories with sub-categories'")
    categories = getExtensionCategories(files)
    categoriesWithSub = getCategoriesWithSubCategories(categories)

    # Collect contributing organizations and individuals
    contributors = getExtensionContributors(files)
    print("\nCollecting extension 'contributing organizations and individuals'")
    (organizations, individuals, extensionsToOrganizations, individualToOrganizations) = \
            getContributingOrganizationsAndIndividuals(contributors)

    return (links, categories, categoriesWithSub, organizations, individuals, individualToOrganizations)

#---------------------------------------------------------------------------
def getExtensionLauncherAdditionalSettingsFromBuildDirs(slicerExtensionIndexBuildDir):
    launcherSettingsFiles = []
    for dirname in os.listdir(slicerExtensionIndexBuildDir):
        extensionBuildDir = os.path.join(slicerExtensionIndexBuildDir, dirname)
        if os.path.isdir(extensionBuildDir):
            if dirname.endswith('-build'):
                launcherSettings = getExtensionLauncherSettings(extensionBuildDir)
                if launcherSettings is not None:
                    launcherSettingsFiles.append(launcherSettings)
    return launcherSettingsFiles

#---------------------------------------------------------------------------
def readAdditionalLauncherSettings(settingsFile, configs):
    """Read ``settingsFile`` and populate the provided ``configs`` dictionnary.
    """
    parser = ConfigParser.ConfigParser()
    parser.read(settingsFile)
    for section in ['LibraryPaths', 'Paths', 'PYTHONPATH', 'QT_PLUGIN_PATH']:
        if not parser.has_section(section):
            continue
        if section not in configs:
            configs[section] = []
        for idx in range(parser.getint(section, 'size')):
            configs[section].append(parser.get(section, '{0}\\path'.format(idx+1)))


#---------------------------------------------------------------------------
def writeLauncherAdditionalSettings(outputSettingsFile, configs):
    """Write ``outputSettingsFile`` using provided ``configs`` dictionnary.
    """
    with open(outputSettingsFile, 'w') as fileContents:
        def _writeSection():
            fileContents.write('[{0}]\n'.format(section))
            items = configs[section]
            size = len(items)
            for idx in range(size):
                fileContents.write('{0}\\path={1}\n'.format(idx+1, items[idx]))
            fileContents.write('size={0}\n'.format(size))
        for section in configs:
            _writeSection()
            fileContents.write('\n')

#---------------------------------------------------------------------------
def mergeExtensionsLauncherAdditionalSettings(slicerExtensionIndexBuildDir):
    # Read extension launcher additional settings
    settingsFiles = getExtensionLauncherAdditionalSettingsFromBuildDirs(slicerExtensionIndexBuildDir)
    configs = {}
    for settingsFile in settingsFiles:
        readAdditionalLauncherSettings(settingsFile, configs)

    # Write common launcher additional settings
    mergedSettingsFile = getPackagesMetadataTopLevelDirectory() + "AdditionalLauncherSettings.ini"
    writeLauncherAdditionalSettings(mergedSettingsFile, configs)

    return mergedSettingsFile

#---------------------------------------------------------------------------
def getSlicerLauncher(slicerBuildDir):
    launcher = os.path.join(slicerBuildDir, 'Slicer')
    if sys.platform.startswith('win'):
        launcher += '.exe'
    if not os.path.exists(launcher):
        return None
    return launcher

#---------------------------------------------------------------------------
def installPip(slicerBuildDir=None):
    url = 'https://bootstrap.pypa.io/get-pip.py'
    filePath = os.path.basename(url)
    print("\nDownloading '{0}' into '{1}'".format(url, filePath))
    response = urllib2.urlopen(url)
    with open(filePath, "wb") as fileContents:
        fileContents.write(response.read())

    print("\nInstalling pip")
    slicerLauncherPopen(getSlicerLauncher(slicerBuildDir), ['--launch', 'python', filePath])

#---------------------------------------------------------------------------
def runPip(args, slicerBuildDir=None):
    def _runPip():
        print("\npip {0}".format(" ".join(args)))
        slicerLauncherPopen(getSlicerLauncher(slicerBuildDir), ['--launch', 'pip'] + args)
    try:
        _runPip()
    except RuntimeError:
        installPip(slicerBuildDir)
        _runPip()

#---------------------------------------------------------------------------
def slicerLauncherPopen(launcher, args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs):
    if launcher is None:
        args.pop(0) # Ignore '--launch' argument
        print("\nStarting {0}".format(" \\\n  ".join(args)))
    else:
        print("\nStarting {0} {1}".format(launcher, " \\\n  ".join(args)))
    p = subprocess.Popen([launcher] + args, stdout=stdout, stderr=stderr, **kwargs)
    ec = p.wait()
    if ec:
        raise RuntimeError, "Calling {0} failed (exit code {1})".format(launcher, ec)
    return p

#---------------------------------------------------------------------------
def getSlicerVersion(slicerBuildDir):
    p = slicerLauncherPopen(getSlicerLauncher(slicerBuildDir), ['--version'])
    if p is None:
        return None
    output = p.stdout.read() # Slicer X.Y.Z[-YYYY-MM-DD]
    version = re.findall(r'^Slicer (\d\.\d)', output)[0]
    print("\nAuto-discovered Slicer version is {}".format(version))
    return version

#---------------------------------------------------------------------------
def getModuleDirectories(basePath, slicerVersion):
    """Recursively walk ``basepath`` directory and return the list of directory expected
    to contain cli, scripted or loadable modules.
    """
    output = []
    for subdir in ['cli-modules', 'qt-loadable-modules', 'qt-scripted-modules']:
        moduleDir = os.path.join(basePath, 'lib', 'Slicer-{0}'.format(slicerVersion), subdir)
        if os.path.isdir(moduleDir):
            output.append(moduleDir)
    if os.path.isdir(basePath):
        for dirname in os.listdir(basePath):
            output.extend(getModuleDirectories(os.path.join(basePath, dirname), slicerVersion))
    return output

#---------------------------------------------------------------------------
def getExtensionLauncherSettings(extensionBuildDir):
    """Recursively walk an extension build directory until a file named
    `AdditionalLauncherSettings.ini` is found.
    """
    for filename in os.listdir(extensionBuildDir):
        filepath = os.path.join(extensionBuildDir, filename)
        if filename == 'AdditionalLauncherSettings.ini':
            return filepath
        elif not os.path.isdir(filepath):
            continue
        else:
            return getExtensionLauncherSettings(filepath)

#---------------------------------------------------------------------------
def isCLIExecutable(filePath):
    import ctk_cli
    result = ctk_cli.isCLIExecutable(filePath)
    if not result:
        return False
    moduleName = extractCLIModuleName(filePath)
    # for pattern in ['Test$']:
    #     if re.search(pattern, moduleName, flags=re.IGNORECASE) is not None:
    #         return False
    return True

#---------------------------------------------------------------------------
def extractCLIModuleName(filePath):
    name = os.path.basename(filePath)
    if name.endswith('.exe'):
        name = result[:-4]
    return name

#---------------------------------------------------------------------------
def isLoadableModule(filePath):
    return extractLoadableModuleName(filePath) is not None

#---------------------------------------------------------------------------
def extractLoadableModuleName(filePath):
    # See qSlicerUtils::isLoadableModule
    result = re.match("(?:libqSlicer(.+)Module\\.(?:so|dylib))|(?:(?!lib)qSlicer(.+)Module\\.(?:dll|DLL))", os.path.basename(filePath))
    name = None
    if result is not None:
        name = result.group(1) if result.group(1) is not None else result.group(2)
    return name

#---------------------------------------------------------------------------
def isScriptedModule(filePath):
    isScript = os.path.splitext(filePath)[-1] == '.py'
    if not isScript:
        return False
    moduleName = extractScriptedModuleName(filePath)
    for pattern in ['Plugin', 'SelfTest', 'Test', '\d{4}', 'Tutorial']:
        if re.search(pattern, moduleName, flags=re.IGNORECASE) is not None:
            return False
    return moduleName

#---------------------------------------------------------------------------
def extractScriptedModuleName(filePath):
    return os.path.splitext(os.path.basename(filePath))[0]

#---------------------------------------------------------------------------
def _getModuleNames(tester, extractor, buildDir):
    names = []
    for path in os.listdir(buildDir):
        filePath = os.path.join(buildDir, path)
        if tester(filePath):
            names.append(extractor(filePath))
    return names

#---------------------------------------------------------------------------
def getCLIModuleNames(buildDir):
    return _getModuleNames(isCLIExecutable, extractCLIModuleName, buildDir)

#---------------------------------------------------------------------------
def getLoadableModuleNames(buildDir):
    return _getModuleNames(isLoadableModule, extractLoadableModuleName, buildDir)

#---------------------------------------------------------------------------
def getScriptedModuleNames(buildDir):
    return _getModuleNames(isScriptedModule, extractScriptedModuleName, buildDir)

#---------------------------------------------------------------------------
def getModuleNamesByType(modulePaths):
    """Return a dictionnary of module types and associated module names
    given a list of module paths.

    .. note::
        Module types are indentified using keys ``cli``, ``loadable`` and ``scripted``.
    """
    results = {
        'cli':[],
        'loadable':[],
        'scripted':[]
        }
    for path in modulePaths:
        results['cli'].extend(getCLIModuleNames(path))
        results['loadable'].extend(getLoadableModuleNames(path))
        results['scripted'].extend(getScriptedModuleNames(path))
    return results

#---------------------------------------------------------------------------
def getBuiltinModulesFromBuildDir(slicerBuildDir, slicerVersion=None):
    """Return list of Slicer built-in module.
    """
    if slicerVersion is None:
        slicerVersion = getSlicerVersion(slicerBuildDir)
    return getModuleNamesByType(getModuleDirectories(slicerBuildDir, slicerVersion))

#---------------------------------------------------------------------------
def getExtensionModuleDirectoriesFromBuildDirs(slicerBuildDir, slicerExtensionIndexBuildDir, slicerVersion=None):
    """Return a dictionnary of extension names with corresponding module directories.
    """
    data = {}
    if slicerVersion is None:
        slicerVersion = getSlicerVersion(slicerBuildDir)
    for dirname in os.listdir(slicerExtensionIndexBuildDir):
        if os.path.isdir(os.path.join(slicerExtensionIndexBuildDir, dirname)):
            if dirname.endswith('-build'):
                extensionName = dirname.replace('-build', '')
                data[extensionName] = getModuleDirectories(os.path.join(slicerExtensionIndexBuildDir, dirname), slicerVersion)
    return data

#---------------------------------------------------------------------------
def getExtensionModulesFromBuildDirs(slicerBuildDir, slicerExtensionIndexBuildDir, slicerVersion=None):
    """Return a dictionnary of extension names with corresponding module names.

    .. note::
        Slicer built-in modules are associated with the special extension name ``builtin``.
        See :func:`getBuiltinModulesFromBuildDir`
    """
    if slicerVersion is None:
        slicerVersion = getSlicerVersion(slicerBuildDir)

    data = {}

    extensionModuleDirectories = getExtensionModuleDirectoriesFromBuildDirs(slicerBuildDir, slicerExtensionIndexBuildDir, slicerVersion)
    for extensionName, extensionModuleDirectory in extensionModuleDirectories.iteritems():
        data[extensionName] = getModuleNamesByType(extensionModuleDirectory)

    data['builtin'] = getBuiltinModulesFromBuildDir(slicerBuildDir, slicerVersion)

    return data

#---------------------------------------------------------------------------
def outputFilePath(path, prefix, system=None, withDate=False):
    """ Return file name suffixed with platform name and optionally today's date::

            <path>/<prefix>_(Linux|Darwin|Windows)[_YYYY-MM-DD].json
    """
    if system is None:
        system = platform.system()
    date = ""
    if withDate:
        date = "_" + datetime.date.today().isoformat()
    fileName = '{0}_{1}{2}.json'.format(prefix, system, date)
    return os.path.join(path, fileName)

#---------------------------------------------------------------------------
def save(filePath, dictionnary):
    """Save dictionnary as a json file`
    """
    with codecs.open(filePath, 'w', 'utf-8') as fileContents:
        fileContents.write(
            json.dumps(dictionnary, sort_keys=True, indent=4))
    print("\nSaved '{}'".format(filePath))
    return filePath

#---------------------------------------------------------------------------
def getLoadedModuleMetadata(module):
    """Return a dictionnary containing the module contributors and categories.
    """
    metadata = {}
    metadata['contributors'] = module.contributors
    metadata['categories'] = module.categories
    return metadata

#---------------------------------------------------------------------------
def getLoadedModulesMetadata():
    """Return a dictionnary containing contributors and categories for
    all modules currently loaded in Slicer.
    """
    import slicer
    metadata = {}
    moduleManager = slicer.app.moduleManager()
    for moduleName in moduleManager.modulesNames():
        metadata[moduleName] = getLoadedModuleMetadata(moduleManager.module(moduleName))
    return metadata

#---------------------------------------------------------------------------
def getModulesMetadataFilePath(system=None):
    return outputFilePath(getPackagesMetadataDataDirectory(), 'slicer-modules-metadata', system=system)

#---------------------------------------------------------------------------
def saveLoadedModulesMetadata():
    """Save metadata associated with modules loaded in Slicer.
    """
    save(getModulesMetadataFilePath(), getLoadedModulesMetadata())

    slicer.app.quit()

#---------------------------------------------------------------------------
def _saveLoadedModulesMetadata(args):
    saveLoadedModulesMetadata()

#---------------------------------------------------------------------------
def getExtensionModulesFilePath(system=None):
    return outputFilePath(getPackagesMetadataDataDirectory(), 'slicer-extension-modules', system=system)

#---------------------------------------------------------------------------
def getExtensionModules():
    cloneRepository(SLICER_PACKAGES_METADATA_GIT_URL, getPackagesMetadataTopLevelDirectory())
    return mergeMetadataFiles('slicer-extension-modules')

#---------------------------------------------------------------------------
def getModules(extensionModules):
    modules = {}
    for extensionName, moduleTypes in extensionModules.iteritems():
        for moduleType, moduleNames in moduleTypes.iteritems():
            for moduleName in moduleNames:
                #print([moduleName, extensionName, moduleType])
                modules[moduleName] = { 'extensionName' : extensionName,
                                        'moduleType' : moduleType }
    return modules

#---------------------------------------------------------------------------
def saveAllExtensionsModulesMetadata(slicerBuildDir, slicerExtensionIndexBuildDir,
        updateGithub=True, slicerVersion=None):

    try:
        import ctk_cli
    except ImportError:
        runPip(['install', 'ctk_cli'], slicerBuildDir=slicerBuildDir)
        import ctk_cli

    if slicerVersion is None:
        slicerVersion = getSlicerVersion(slicerBuildDir)

    # Clone repository
    repo = cloneRepository(SLICER_PACKAGES_METADATA_GIT_URL, getPackagesMetadataTopLevelDirectory())

    mergedSettingsFile = mergeExtensionsLauncherAdditionalSettings(slicerExtensionIndexBuildDir)

    launcherArgs = ['--launcher-additional-settings', mergedSettingsFile]

    extensionModuleDirectories = \
        getExtensionModuleDirectoriesFromBuildDirs(slicerBuildDir, slicerExtensionIndexBuildDir, slicerVersion).values()
    # Flatten list
    extensionModuleDirectories = [item for sublist in extensionModuleDirectories for item in sublist]

    launcherArgs.append('--ignore-slicerrc')
    launcherArgs.append('--no-main-window')
    launcherArgs.append('--python-script')
    launcherArgs.append(os.path.realpath(__file__))
    launcherArgs.append('save-loaded-modules-metadata')

    if len(extensionModuleDirectories) > 0:
        launcherArgs.append('--additional-module-paths')
        launcherArgs.extend(extensionModuleDirectories)

    launcher = getSlicerLauncher(slicerBuildDir)
    p = slicerLauncherPopen(launcher, launcherArgs)
    if p is None:
        return None
    print("\nSaved '{0}'".format(getModulesMetadataFilePath()))

    data = getExtensionModulesFromBuildDirs(slicerBuildDir, slicerExtensionIndexBuildDir, slicerVersion)
    save(getExtensionModulesFilePath(), data)

    if updateGithub:
        index = repo.index
        index.add([getModulesMetadataFilePath()])
        index.add([getExtensionModulesFilePath()])
        msg = "Update modules-metadata and modules-by-extension listings for {0} platform".format(platform.system())
        index.commit(msg)
        print("\nCommit: {0}".format(msg))
        repo.remotes.origin.push(repo.head)
        print("\nPushed changed to '{0}'".format(SLICER_PACKAGES_METADATA_GIT_URL))

#---------------------------------------------------------------------------
def _saveAllExtensionsModulesMetadata(args):

    if args.slicer_version is None:
        args.slicer_version = getSlicerVersion(args.slicer_build_dir)

    saveAllExtensionsModulesMetadata(
        args.slicer_build_dir,
        args.slicer_extension_index_build_dir,
        updateGithub=not args.no_github_update,
        slicerVersion=args.slicer_version)

#---------------------------------------------------------------------------
def updateWiki(slicerBuildDir, wikiName='slicer', updateWiki=True, slicerVersion=None):

    try:
        import mwclient
    except ImportError:
        runPip(['install', 'mwclient==0.6.5'], slicerBuildDir=slicerBuildDir)
        import mwclient

    # Update python path to ensure 'SlicerWizard' module can be imported
    wizardPath = os.path.join(slicerBuildDir, 'bin', 'Python')
    if wizardPath not in sys.path:
        sys.path.append(wizardPath)

    if slicerVersion is None:
        slicerVersion = getSlicerVersion(slicerBuildDir)

    # Extension metadata
    (extensionLinks, extensionCategories, extensionCategoriesWithSub, extensionOrganizations, extensionIndividuals, individualToOrganizationsForExtensions) = \
            getExtensionsMetadata(slicerVersion, wikiName)

    # Module metadata
    (moduleLinks, moduleCategories, moduleCategoriesWithSub, moduleOrganizations, moduleIndividuals, individualToOrganizationsForModules) = \
            getModulesMetadata(wikiName)

    # Individual to organization metadata
    individualToOrganizations = _merge(dict(individualToOrganizationsForExtensions), individualToOrganizationsForModules)

    # Extension to module metadata
    modules = getModules(getExtensionModules())

    # Module by types
    moduleTypes = {}
    for name in modules:
        moduleType = modules[name]['moduleType']
        if moduleType not in moduleTypes:
            moduleTypes[moduleType] = []
        if name in moduleLinks:
            moduleTypes[moduleType].append(name)

    withSectionToc = True

    #-----------------------------------------------------------------------
    def _updateModuleLink(name, moduleLink):
        if name in modules:
            extensionName = modules[name]['extensionName']
            if extensionName in extensionLinks:
                extensionItem = extensionLinks[extensionName]
                if moduleLinks[name]['type'] == WIKI_LINK_OFF:

                    moduleLink["wikilink"] = \
                        _generateWikiLink(extensionItem['type'],
                                                        'Extensions',
                                                        extensionName,
                                                        prettify(name),
                                                        extensionItem['url'])
        return moduleLink

    moduleLinks = {k:_updateModuleLink(k, v) for (k,v) in moduleLinks.iteritems()}

    #-----------------------------------------------------------------------
    def _excludeModule(name):
        categories = moduleCategories[name]
        for category in categories:
            if category.split('.')[0] in ['Legacy', 'Testing', 'Developer Tools']:
                return True
            for subcategory in category.split('.'):
                if subcategory in ['Test']:
                    return True
            if re.search('SelfTest', name, flags=re.IGNORECASE) is not None:
                return True
        return False

    moduleLinksFiltered = \
        {k:v for (k,v) in moduleLinks.iteritems() if not _excludeModule(k)}

    # Cache dictionnaries so that they can be re-used from the link renderer
    setCacheEntry("modules", modules)
    setCacheEntry("extensionLinks", extensionLinks)
    setCacheEntry("individualToOrganizations", individualToOrganizations)

    moduleLinksRenderer = (headerForWikiList, moduleLinkAsListItem, headerForWikiList)

    # Generate wiki page
    sections = []

    sections.append(itemByNameToWiki('Modules',
                    moduleLinksFiltered,
                    linksRenderer=moduleLinksRenderer))

    sections.append(itemByCategoryToWiki('Modules', moduleLinks,
                    moduleCategoriesWithSub,
                    linksRenderer=moduleLinksRenderer,
                    withToc=withSectionToc))

    sections.append(itemByPropertyToWiki('Modules', moduleLinks,
                    "contributing organization", moduleOrganizations,
                    linksRenderer=moduleLinksRenderer,
                    withToc=withSectionToc))

    sections.append(itemByPropertyToWiki('Modules', moduleLinks,
                    "contributing individual", moduleIndividuals,
                    tocEntryRenderer=individualEntryAsWikiListItem,
                    linksRenderer=moduleLinksRenderer,
                    withToc=withSectionToc))

    sections.append(itemByPropertyToWiki('Modules', moduleLinks,
                    "type", moduleTypes,
                    linksRenderer=moduleLinksRenderer,
                    withToc=withSectionToc))

    sections.append(itemByNameToWiki('Extensions', extensionLinks))

    sections.append(itemByCategoryToWiki('Extensions', extensionLinks,
                    extensionCategoriesWithSub,
                    withToc=withSectionToc))

    sections.append(itemByPropertyToWiki('Extensions', extensionLinks,
                    "contributing organization", extensionOrganizations,
                    withToc=withSectionToc))

    sections.append(itemByPropertyToWiki('Extensions', extensionLinks,
                    "contributing individual", extensionIndividuals,
                    withToc=withSectionToc))

    lines = []
    if withSectionToc:
        lines.append('__NOTOC__')
        for (title, anchor, content) in sections:
            lines.append("* [[{0}|{1}]]".format(anchor, title))

    for (title, anchor, content) in sections:
        lines.extend(content)

    if updateWiki:
        result = saveWikiPage(wikiName, 'User:UpdateBot/Issue-2843-Consolidated-Extension-List', \
                     "This page has been updated based on the list of extension description files available on the ExtensionsIndex", \
                     "\n".join(lines))
        print(result)

#---------------------------------------------------------------------------
def _updateWiki(args):
    if args.cache_wiki_query:
        loadPersistentCache()
    setCacheEntry("wiki-slicer-password", args.slicer_wiki_password)
    updateWiki(args.slicer_build_dir,
        updateWiki=not args.no_wiki_update,
        slicerVersion=args.slicer_version)

#---------------------------------------------------------------------------
setCacheEntry("wiki-slicer-username", "UpdateBot")
setCacheEntry("wiki-slicer-host", "slicer.org")
setCacheEntry("wiki-slicer-path", "/slicerWiki/")

#---------------------------------------------------------------------------
if __name__ == '__main__':

    import argparse

    #=======================================================================
    class VerboseErrorParser(argparse.ArgumentParser):
        #-------------------------------------------------------------------
        def error(self, message):
            sys.stderr.write('error: %s\n' % message)
            self.print_help(sys.stderr)
            sys.exit(2)

    #-----------------------------------------------------------------------
    def _add_common_args(parser):
        parser.add_argument('slicer_build_dir',
            help='path to slicer inner build directory')

        parser.add_argument('--slicer-version', dest='slicer_version', default=None,
            help='slicer version to consider. By default, the slicer version '
            'is autodiscovered running Slicer build directory.')

    parser = VerboseErrorParser(description='generate and publish Slicer extensions and modules list on the Slicer wiki')
    commands = parser.add_subparsers()

    #---
    wiki_parser = commands.add_parser(
        'update-wiki', help = 'update Slicer wiki')

    _add_common_args(wiki_parser)

    wiki_parser.add_argument('slicer_wiki_password',
        help='slicer wiki password')

    wiki_parser.add_argument('--cache-wiki-query', dest='cache_wiki_query',
        action='store_true',
        help='cache result of wiki query (for debugging)')

    wiki_parser.add_argument('--no-wiki-update', dest='no_wiki_update',
        action='store_true',
        help='disable wiki update')

    wiki_parser.set_defaults(action=_updateWiki)

    #--
    save_loaded_parser = commands.add_parser(
        'save-loaded-modules-metadata', help = 'save metadata of all Slicer modules (should be used in running Slice instance)')
    save_loaded_parser.set_defaults(action=_saveLoadedModulesMetadata)

    #--
    saveAll_parser = commands.add_parser(
        'publish-extension-module-metadata', help = 'publish metadata of all Slicer modules')

    _add_common_args(saveAll_parser)

    saveAll_parser.add_argument('slicer_extension_index_build_dir',
        help='path to slicer extension index top-level build directory')

    saveAll_parser.add_argument('--no-github-update', dest='no_github_update',
        action='store_true',
        help='disable github update')

    saveAll_parser.set_defaults(action=_saveAllExtensionsModulesMetadata)

    args = parser.parse_args()

    if 'slicer_extension_index_build_dir' in args:
        args.slicer_extension_index_build_dir = os.path.expanduser(args.slicer_extension_index_build_dir)

    if 'slicer_build_dir' in args:
        args.slicer_build_dir = os.path.expanduser(args.slicer_build_dir)

    args.action(args)
