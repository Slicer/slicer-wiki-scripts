#!/usr/bin/env python

import json
import urllib
import urllib2
import sys
import argparse

#---------------------------------------------------------------------------
def getSlicerReleases():
    """Return dictionnary of Slicer release and associated Slicer revision.
    The list of revision for each release is reported here:
      http://wiki.slicer.org/slicerWiki/index.php/Release_Details
    """
    return {
        '4.0.0' : '18777',
        '4.0.1' : '19033',
        '4.1.0' : '19886',
        '4.1.1' : '20313',
        '4.2.0' : '21298',
        '4.2.1' : '21438',
        '4.2.2' : '21508',
        '4.2.2-1' : '21513',
        '4.3.0' : '22408',
        '4.3.1' : '22599',
        '4.3.1-1' : '22704',
        '4.4.0' : '23774'
    }

#---------------------------------------------------------------------------
def getSlicerRevision(release):
    """Return Slicer revision that corresponds to a Slicer release.
    Otherwise, return ``None``.
    """
    releases = getSlicerReleases()
    if release not in releases:
        return None
    return releases[release]

#---------------------------------------------------------------------------
def getSlicerRevisions():
    return {y:x for x,y in getSlicerReleases().iteritems()}

#---------------------------------------------------------------------------
def getSlicerRelease(revision):
    """Return Slicer release that corresponds to a Slicer revision.
    Otherwise, return ``None``.
    """
    revisions = getSlicerRevisions()
    if revision not in revisions:
        return None
    return revisions[revision]

#---------------------------------------------------------------------------
def _call_midas_url(url, data):
    url_values = urllib.urlencode(data)
    full_url = url + '?' + url_values
    response = urllib2.urlopen(full_url)
    response_read = response.read()
    response_dict = json.loads(response_read)
    response_data = response_dict['data']
    return response_data

#---------------------------------------------------------------------------
def getExtensionListByName(url, extensionName, release=None):
    """By default, return list of all extensions with ``extensionName``.
    """
    method = 'midas.slicerpackages.extension.list'
    codebase = 'Slicer4'
    data = {'method': method, 'codebase': codebase, 'productname': extensionName}
    slicer_revision = None
    if release is not None:
        slicer_revision = getSlicerRevision(release)
    if slicer_revision is not None:
        data['slicer_revision'] = slicer_revision
    return _call_midas_url(url, data)

#---------------------------------------------------------------------------
def getExtensionById(url, extensionId):
    """Return property associated with extension identified by ``extensionId``.
    """
    method = 'midas.slicerpackages.extension.list'
    codebase = 'Slicer4'
    data = {'method': method, 'codebase': codebase, 'extension_id': extensionId}
    extensions = _call_midas_url(url, data)
    if len(extensions) > 0:
        return extensions[0]
    else:
        return []

#---------------------------------------------------------------------------
def getItemById(url, itemId):
    """Return property associated with item identified by ``itemId``.
    """
    method = 'midas.item.get'
    data = {'method': method, 'id': itemId}
    return _call_midas_url(url, data)

#---------------------------------------------------------------------------
def getExtensionSlicerRevisionAndDownloads(url, extensionName,verbose):
    """Return a dictionnary of slicer revision and download counts for
    the given ``extensionName``.
    """
    if verbose==True:
        print("\n  Collecting 'extension_id' / 'item_id' pair matching '{0}' name".format(extensionName))
    all_itemids = [(ext['item_id'], ext['extension_id']) for ext in getExtensionListByName(url, extensionName)]

    item_rev_downloads = {}
    if verbose==True:
        print("\n  Collecting `slicer_revision` and `download` for 'extension_id' / 'item_id' pair")
    for (idx, (itemid, extensionid)) in enumerate(all_itemids):
        #print("{0}/{1}".format(idx+1, len(all_itemids)))
        if verbose==True and idx % 5 == 0:
            print("  {:.0%}".format(float(idx) / len(all_itemids)))

        item_rev_downloads[itemid] = [getItemById(url, itemid)['download'], getExtensionById(url, extensionid)['slicer_revision']]

    if verbose==True:
        print("\n  Consolidating `download` by 'slicer_revision'")
    rev_downloads = {}
    for (itemid, downloads_rev) in item_rev_downloads.iteritems():
        downloads = int(downloads_rev[0])
        rev = downloads_rev[1]
        if downloads == 0:
            continue
        if rev not in rev_downloads:
            rev_downloads[rev] = downloads
        else:
            rev_downloads[rev] += downloads

    return {key: rev_downloads[key] for key in sorted(rev_downloads)}

#---------------------------------------------------------------------------
def getExtensionDownloadStatsByRelease(extension_slicer_revision_downloads,verbose):
    """Given a dictionnary of slicer_revision and download counts, this function
    return a dictionnary release and download counts.
    Downloads associated with nightly build happening between release A and B are
    associated with A-nightly "release".
    """
    post_release = None
    pre_release_downloads = 0
    release_downloads = {}
    for (revision, downloads) in extension_slicer_revision_downloads.iteritems():
        release = getSlicerRelease(revision)
        if release:
            release_downloads[release] = downloads
            post_release = release + '-nightly'
        else:
            if post_release is not None:
                if post_release not in release_downloads:
                    release_downloads[post_release] = downloads
                else:
                    release_downloads[post_release] += downloads
            else:
                pre_release_downloads += downloads

    if pre_release_downloads:
        releases = getSlicerReleases().keys()
        release_for_pre_release = releases[releases.index(release_downloads.keys()[0]) - 1]
        release_downloads[release_for_pre_release + '-nightly'] = pre_release_downloads

    return release_downloads

#---------------------------------------------------------------------------
def getExtensionDownloadStats(url, extensionName,verbose):
    """Return download stats associated with ``extensionName``.
    """
    if verbose==True:
        print("\nRetrieving '{0}' extension download statistics from '{1}' server".format(extensionName, url))
    rev_downloads = getExtensionSlicerRevisionAndDownloads(url, extensionName,verbose)
    if verbose==True:
        print("\n  Grouping `download` by 'release'")
    return getExtensionDownloadStatsByRelease(rev_downloads,verbose)


#---------------------------------------------------------------------------
if __name__ == '__main__':
    parser = argparse.ArgumentParser(prog=sys.argv[0],description="Retrieves the extension download statistics grouped by release")
#    parser.usage('%(prog)s [-h] extension1 [extension2 ...]')
    parser.add_argument("names", metavar='extensions',nargs='+',help="Extension names")
    parser.add_argument("-v", "--verbose", help="increase output verbosity",action="store_true")
    args = parser.parse_args()
    listExtensions=args.names
    if args.verbose==True:  
        print("List of extensions: "+str(listExtensions))
    url = 'http://slicer.kitware.com/midas3/api/json'
    for extensionName in listExtensions:
        if args.verbose==True:
            print("*****************************************************")
            print("*****************************************************")
            print("Extension Name: "+extensionName)
            print("*****************************************************")
        print(extensionName+": "+str(getExtensionDownloadStats(url, extensionName,args.verbose)))
