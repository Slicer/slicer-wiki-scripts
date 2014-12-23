*******************
Slicer Wiki Scripts
*******************

========
Overview
========

You will find here scripts allowing to automate the maintenance of
the Slicer wiki.


=======
Scripts
=======

---------------------------------------
slicer_wiki_extension_module_listing.py
---------------------------------------

This script is useful to automatically create the listing of Slicer modules
and extensions available on the Slicer wiki user documentation.

The creation of the listing is a two-step process:

* Step 1: On each factory (Linux, MacOSX, Windows):

  (a) the list of modules built in every extension is generated
  (b) Slicer is started to find out which modules can be loaded successfully into Slicer, the list of modules (as associated metadata) is then published into a github repository: 

     https://github.com/Slicer/slicer-packages-metadata

* Step 2: Creation of consolidated listing of modules and extensions by downloading the metadata generated in the previous step and downloading the associated list of extension description files.


Prerequisites:

.. code:: bash

  pip install --pre gitpython



=========
Licensing
=========

Materials in this repository are distributed under the following licenses:

* All software is licensed under BSD style license, with extensions to cover
contributions and other issues specific to 3D Slicer. 
See License.txt file for details.
