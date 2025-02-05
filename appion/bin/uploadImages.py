#!/usr/bin/env python

import os
import time
import glob
import numpy
import string
import shutil
import leginon.leginondata
import leginon.projectdata
import leginon.ddinfo
from pyami import mrc, fileutil, numpil
from appionlib import appionScript
from appionlib import apDisplay
from appionlib import apParam
from appionlib import apFile
from appionlib import apDBImage

#=====================
#=====================
class UploadImages(appionScript.AppionScript):
	#=====================
	def setupParserOptions(self):
		self.parser.add_option("--mpix", "--pixel-size", dest="mpix", type="float",
			help="Pixel size of the images in meters", metavar="#.#")
		self.parser.add_option("--mag", dest="magnification", type="int", metavar="MAG",
			help="nominal magnification, e.g., --mag=50000 for 50kX")
		self.parser.add_option("--kv", dest="kv", type="int", metavar="INT",
			help="high tension (in kilovolts), e.g., --kv=120")

		self.parser.add_option("--cs", dest="cs", type="float", metavar="#.#",
			default=2.0, help="spherical aberration constant (in mm), e.g., --cs=2.0")

		self.parser.add_option("--image-dir", dest="imagedir",
			help="Directory that contains MRC files to upload", metavar="DIR")

		self.parser.add_option("--leginon-output-dir", dest="leginondir",
			help="Leginon output directory, e.g., --leginon-output-dir=/data/leginon",
			metavar="DIR")

		self.parser.add_option("--images-per-series", dest="seriessize", type="int", default=1,
			help="Number of images in tilt series", metavar="#")

		self.parser.add_option("--angle-list", dest="angleliststr",
			help="List of angles in radians to apply to tilt series", metavar="#,#,#")
		self.parser.add_option("--dose-list", dest="doseliststr",
			help="List of doses in e-/A^2 to apply to tilt series", metavar="#,#,#")
		self.parser.add_option("--defocus-list", dest="defocusliststr",
			help="List of defoci in meters to apply to defocal series", metavar="#,#,#")
		self.parser.add_option("--defocus", dest="defocus", type="float",
			help="Defocus in meters to apply to all images", metavar="#.#e#")
		self.parser.add_option("--invert", dest="invert", default=False,
			action="store_true", help="Invert image density")
		self.parser.add_option("--azimuth", dest="azimuth", type="float",
			help="Tilt azimuth from y-axis in degrees", metavar="#.#")

		self.uploadtypes = ('tiltseries', 'defocalseries', 'normal')
		self.parser.add_option("--type", dest="uploadtype", default="normal",
			type="choice", choices=self.uploadtypes,
			help="Type of upload to perform: "+str(self.uploadtypes), metavar="..")

		self.parser.add_option("--norm", dest="normimg", type="string", metavar="PATH",
			help="normalization image to apply to each upload")
		self.parser.add_option("--dark", dest="darkimg", type="string", metavar="PATH",
			help="dark image to apply to each upload frame")
		# option: give sessionname
		self.parser.add_option("--session", dest="sessionname", type="string", metavar="NAME",
			help="session name")
		# link to parent image
		self.parser.add_option("--parentid", dest="target_parent", type="int", metavar="ID",
			help="parent image id in the session to link to as a target")
		self.parser.add_option("--presetimgid", dest="preset_imgid", type="int", metavar="ID",
			help="An image id in the session to propogate imaging condition on instead of Appion Instrument")

	#=====================
	def checkConflicts(self):
		if self.params['description'] is None:
			apDisplay.printError("Please provide a description, e.g., --description='test'")
		if self.params['imagedir'] is None:
			apDisplay.printError("Please provide a image directory, e.g., --imagedir=/path/to/files/")
			if not os.path.isdir(self.params['imagedir']):
				apDisplay.printError("Image directory '%s' does not exist"%(self.params['imagedir']))
		if self.params['preset_imgid'] is None:
			if self.params['kv'] is None:
				apDisplay.printError("Please provide a high tension (in kV), e.g., --kv=120")
				if self.params['kv'] > 1000:
					apDisplay.printError("High tension must be in kilovolts (e.g., --kv=120)")
			if self.params['magnification'] is None:
				apDisplay.printError("Please provide a magnification, e.g., --mag=50000")		
			if self.params['mpix'] is None:
				apDisplay.printError("Please provide a pixel size (in meters), e.g., --pixelsize=1.3e-10")

		### series only valid with non-normal uploads
		if self.params['seriessize'] is None and self.params['uploadtype'] != "normal":
			apDisplay.printError("If using tilt or defocal series, please provide --images-per-series")
		if self.params['seriessize'] > 1 and self.params['uploadtype'] == "normal":
			apDisplay.printError("If using normal mode, do NOT provide --images-per-series")

		### angleliststr only valid with tiltseries uploads
		if self.params['angleliststr'] is None and self.params['uploadtype'] == "tiltseries":
			apDisplay.printError("If using tilt series, please provide --angle-list")
		if self.params['angleliststr'] is not None and self.params['uploadtype'] != "tiltseries":
			apDisplay.printError("If not using tilt series, do NOT provide --angle-list")
		if self.params['angleliststr'] is not None:
			self.anglelist = self.convertStringToList(self.params['angleliststr'])
			if len(self.anglelist) != self.params['seriessize']:
				apDisplay.printError("'images-per-tilt-series' and 'angle-list' have different lengths")
		### doseliststr only valid with tiltseries uploads
		if self.params['doseliststr'] is not None and self.params['uploadtype'] != "tiltseries":
			apDisplay.printError("If not using tilt series, do NOT provide --dose-list")
		if self.params['doseliststr'] is not None:
			self.doselist = self.convertStringToList(self.params['doseliststr'])
			if len(self.doselist) != self.params['seriessize']:
				apDisplay.printError("'images-per-tilt-series' and 'dose-list' have different lengths")

		### defocusliststr only valid with non-normal uploads
		if self.params['defocus'] is not None and self.params['defocusliststr'] is not None:
			apDisplay.printError("Please provide only one of --defocus or --defocus-list")
		if self.params['defocus'] is None and self.params['defocusliststr'] is None:
			apDisplay.printError("Please provide either --defocus or --defocus-list")
		if self.params['defocusliststr'] is not None and self.params['uploadtype'] == "normal":
			apDisplay.printError("If using normal mode, do NOT provide --defocus-list")
		if self.params['defocusliststr'] is not None:
			self.defocuslist = self.convertStringToList(self.params['defocusliststr'])
			if len(self.defocuslist) != self.params['seriessize']:
				apDisplay.printError("'images-per-tilt-series' and 'defocus-list' have different lengths")

		if self.params['defocus'] == 0:
			# ok if use 0.0 or 0
			pass
		### check for negative defoci
		elif self.params['defocus'] is not None and self.params['defocus'] > 0:
			apDisplay.printWarning("defocus is being switched to negative, %.3f"
				%(self.params['defocus']))
			self.params['defocus'] *= -1.0
			if self.params['defocus'] > -0.1:
				apDisplay.printError("defocus must be in microns, %.3f"
					%(self.params['defocus']))
		elif self.params['defocus'] is None:
			# use defocuslist
			newlist = []
			for defocus in self.defocuslist:
				if defocus > 0:
					apDisplay.printWarning("defocus is being switched to negative, %.3f"
						%(defocus))
					defocus *= -1.0
					if defocus > -0.1:
						apDisplay.printError("defocus must be in microns, %.3f"%(defocus))
				newlist.append(defocus)
			self.defocuslist = newlist

		### set session name if undefined
		if not 'sessionname' in self.params or self.params['sessionname'] is None:
			self.params['sessionname'] = self.getUnusedSessionName()
		if self.params['preset_imgid']:
			# Validate that preset_image is in the session
			in_session = self.isImageIdInSession(self.params['preset_imgid'], self.params['sessionname'])
			if not in_session:
				apDisplay.printError("Preset image must be in the session named %s " % (self.params['sessionname'],))

		### set leginon dir if undefined
		if self.params['leginondir'] is None:
			try:
				self.params['leginondir'] = leginon.leginonconfig.unmapPath(leginon.leginonconfig.IMAGE_PATH).replace('\\','/')
			except AttributeError:
				apDisplay.printError("Please provide a leginon output directory, "
					+"e.g., --leginon-output-dir=/data/leginon")
		self.leginonimagedir = os.path.join(self.params['leginondir'], self.params['sessionname'], 'rawdata')
		self.leginonframedir = leginon.ddinfo.getRawFrameSessionPathFromSessionPath(self.leginonimagedir)

		# norm and dark images
		if self.params['normimg'] is not None:
			if not os.path.exists(self.params['normimg']):
				apDisplay.printError("specified image path for normalization '%s' does not exist\n"%self.params['normimg'])
		if self.params['normimg'] is None and self.params['darkimg'] is not None:
			apDisplay.printError("Only dark but not normalization image is not enough forcorrection")

	#=====================
	def convertStringToList(self, string):
		"""
		convert a string containing commas to a list
		"""
		if not "," in string:
			apDisplay.printError("Unable to parse string"%(string))
		stripped = string.strip()
		rawlist = stripped.split(",")
		parsedlist = []
		for item in rawlist:
			if not item:
				continue
			num = float(item)
			parsedlist.append(num)
		return parsedlist

	#=====================
	def getUserData(self):
		username = apParam.getUsername()
		userq = leginon.leginondata.UserData()
		userq['username'] = username
		userdatas = userq.query(results=1)
		if not userdatas:
			return None
		return userdatas[0]

	#=====================
	def isImageIdInSession(self, imageid, sessionname):
		r = leginon.leginondata.SessionData(name=sessionname).query()
		if r:
			image = leginon.leginondata.AcquisitionImageData().direct_query(imageid)
			apDisplay.printColor('Preset image is set to %s' % (image['filename']),'cyan')
			if image['session'].dbid == r[0].dbid:
				return True
		return False

	#=====================
	def getUnusedSessionName(self):
		### get standard appion time stamp, e.g., 10jun30
		sessionq = leginon.leginondata.SessionData()
		sessionq['name'] = self.params['runname']
		sessiondatas = sessionq.query(results=1)
		if not sessiondatas:
			return self.params['runname']

		apDisplay.printColor("Found session name with runname %s, creating new name"%(self.params['runname']), "blue")
		print(sessiondatas[0])

		for char in string.lowercase:
			sessionname = self.timestamp+char
			sessionq = leginon.leginondata.SessionData()
			sessionq['name'] = sessionname
			sessiondatas = sessionq.query(results=1)
			if not sessiondatas:
				break
		return sessionname

	#=====================
	def setSession(self):
		if self.params['sessionname']:
			r = leginon.leginondata.SessionData(name=self.params['sessionname']).query()
			if r:
				self.sessiondata = r[0]
				return
		self.createNewSession()

	#=====================
	def createNewSession(self):
		apDisplay.printColor("Creating a new session", "cyan")

		### get user data
		userdata = self.getUserData()

		sessionq = leginon.leginondata.SessionData()
		sessionq['name'] = self.params['sessionname']
		sessionq['image path'] = self.leginonimagedir
		sessionq['frame path'] = self.leginonframedir
		sessionq['comment'] = self.params['description']
		sessionq['user'] = userdata
		sessionq['hidden'] = False
		sessionq['uid'] = os.getuid()
		sessionq['gid'] = os.getgid()

		projectdata = leginon.projectdata.projects.direct_query(self.params['projectid'])

		projectexpq = leginon.projectdata.projectexperiments()
		projectexpq['project'] = projectdata
		projectexpq['session'] = sessionq
		if self.params['commit'] is True:
			projectexpq.insert()

		self.sessiondata = sessionq
		apDisplay.printColor("Created new session %s"%(self.params['sessionname']), "cyan")
		return

	#=====================
	def setRunDir(self):
		"""
		This function is only run, if --rundir is not defined on the commandline
		"""
		### set the rundir to the leginon image directory
		self.params['rundir'] = self.leginonimagedir

	#=====================
	def setPresetImage(self):
		self.preset_image = None
		if self.params['preset_imgid']:
			# set instrument according to self.preset_image
			self.preset_image = leginon.leginondata.AcquisitionImageData().direct_query(self.params['preset_imgid'])
			return
		return None

	#=====================
	def setInstruments(self):
		if self.preset_image:
			self.temdata = self.preset_image['scope']['tem']
			self.camdata = self.preset_image['camera']['ccdcamera']
			return
		# set appion instruments
		return self.setAppionInstruments()

	#=====================
	def setAppionInstruments(self):
		instrumentq = leginon.leginondata.InstrumentData()
		instrumentq['hostname'] = "appion"
		instrumentq['name'] = "AppionTEM"
		instrumentq['cs'] = self.params['cs'] * 1e-3
		self.temdata = instrumentq
		
		instrumentq = leginon.leginondata.InstrumentData()
		instrumentq['hostname'] = "appion"
		instrumentq['name'] = "AppionCamera"
		self.camdata = instrumentq
		return

	def getFileFormat(self, path):
		extension = os.path.splitext(path)[1]
		if extension in ('.mrc', '.mrcs'):
			return 'mrc'
		if extension in ('.tiff', '.tif'):
			return 'tif'
		return extension[1:]

	#=====================
	def getImagesInDirectory(self, directory):
		searchstring = os.path.join(directory, "*.mrc*")
		apDisplay.printMsg("searching for %s" % searchstring)
		mrclist = glob.glob(searchstring)
		if len(mrclist) == 0:
			searchstring = os.path.join(directory, "*.tif*")
			apDisplay.printMsg("searching for %s" % searchstring)
			mrclist = glob.glob(searchstring)
			if len(mrclist) == 0:
				apDisplay.printError("Did not find any images to upload")
		mrclist.sort()
		return mrclist

	def makeScopeEMData(self):
		### setup scope data
		scopedata = leginon.leginondata.ScopeEMData()
		scopedata['session'] = self.sessiondata
		scopedata['tem'] = self.temdata
		scopedata['magnification'] = self.params['magnification']
		scopedata['high tension'] = self.params['kv']*1000
		scopedata['defocus'] = 0.0
		# These are queried in myamiweb as imageinfo.  Need to be defined
		# so that the first upload will populate the column
		scopedata['stage position'] = { 'x': 0.0, 'y': 0.0, 'z': 0.0, 'a': 0.0, }
		scopedata['image shift'] = { 'x': 0.0, 'y': 0.0 }
		scopedata['beam tilt'] = { 'x': 0.0, 'y': 0.0 }
		return scopedata

	def makeCameraEMData(self,dimension={'x':1,'y':1}, nframes=1):
		### setup camera data
		cameradata = leginon.leginondata.CameraEMData()
		cameradata['session'] = self.sessiondata
		cameradata['ccdcamera'] = self.camdata
		cameradata['dimension'] = dimension
		cameradata['binning'] = {'x': 1, 'y': 1}
		cameradata['frame time'] = 100.0
		cameradata['nframes'] = nframes
		cameradata['save frames'] = False
		cameradata['exposure time'] = 100.0
		# sensor pixel size in meter is required for frealign preparation Bug #4088
		sensor_pixelsize = self.params['magnification'] * self.params['mpix']
		cameradata['pixel size'] = {'x':sensor_pixelsize,'y':sensor_pixelsize}

		return cameradata

	#=====================
	def setDefocalTargetData(self, seriescount):
		if self.params['uploadtype'] != "defocalseries":
			return None

		### setup preset data
		targetpresetdata = leginon.leginondata.PresetData()
		targetpresetdata['session'] = self.sessiondata
		targetpresetdata['tem'] = self.temdata
		targetpresetdata['ccdcamera'] = self.camdata
		targetpresetdata['magnification'] = self.params['magnification']
		targetpresetdata['name'] = 'target'

		targetcameradata = self.makeCameraEMData()

		targetscopedata = self.makeScopeEMData()

		### setup target parent image data
		targetimgdata = leginon.leginondata.AcquisitionImageData()
		targetimgdata['session'] = self.sessiondata
		targetimgdata['scope'] = targetscopedata
		targetimgdata['camera'] = targetcameradata
		targetimgdata['preset'] = targetpresetdata
		targetimgdata['label'] = 'UploadTarget'
		targetimgdata['image'] = numpy.ones((1,1))

		### required
		targetimgdata['filename'] = "null"

		### setup target data
		targetdata = leginon.leginondata.AcquisitionImageTargetData()
		targetdata['session'] = self.sessiondata
		targetdata['image'] = targetimgdata
		targetdata['scope'] = targetscopedata
		targetdata['camera'] = targetcameradata
		targetdata['preset'] = targetpresetdata
		targetdata['type'] = "upload"
		targetdata['version'] = 0
		targetdata['number'] = seriescount
		targetdata['status'] = "done"

		return targetdata

	#=====================
	def linkTargetParent(self,parentimage):
		'''
		Include a fake target that links a parent image with the uploads.
		All images are set as the same target
		'''
		if parentimage['session'].dbid != self.sessiondata.dbid:
			apDisplay.printWarning('parent image not in session.  Will not link target to it')
			return None
		# get targetlist for parent
		r = leginon.leginondata.ImageTargetListData(image=parentimage).query(results=1)
		if not r:
			return None
		targetlist = r[0]
		# get newest target number.  Usually there is no target in this list.
		# otherwise won't be doing this.
		r = leginon.leginondata.AcquisitionImageTargetData(list=targetlist).query()
		newest_number = 0
		for t in r:
			if newest_number < t['number']:
				newest_number = t['number']
		### setup target data
		targetdata = leginon.leginondata.AcquisitionImageTargetData()
		targetdata['session'] = self.sessiondata
		targetdata['image'] = parentimage
		targetdata['scope'] = parentimage['scope']
		targetdata['camera'] = parentimage['camera']
		targetdata['preset'] = parentimage['preset']
		targetdata['type'] = "acquisition"
		targetdata['version'] = 0
		targetdata['delta column'] = 0
		targetdata['delta row'] = 0
		targetdata['number'] = newest_number + 1
		targetdata['status'] = "done"
		return targetdata

	#=====================
	def getTiltSeries(self, seriescount):
		if self.params['uploadtype'] != "tiltseries":
			return None

		tiltq = leginon.leginondata.TiltSeriesData()
		tiltq['session'] = self.sessiondata
		tiltq['number'] = seriescount

		return tiltq

	#=====================
	def getTiltAngle(self, numinseries):
		"""
		get tilt angle from list, if no list return 0.0

		Note: numinseries starts at 1
		"""
		if self.params['angleliststr'] is not None:
			return self.anglelist[numinseries-1]
		return 0.0

	#=====================
	def getDose(self, numinseries):
		"""
		get dose from list, if no list return empty

		Note: numinseries starts at 1
		"""
		if self.params['doseliststr'] is not None:
			return self.doselist[numinseries-1]
		return

	#=====================
	def getImageDefocus(self, numinseries):
		"""
		get defocus from list, if no list return 'defocus' variable

		Note: numinseries starts at 1
		"""
		if self.params['defocus'] is None:
			return self.defocuslist[numinseries-1]
		return self.params['defocus']

	#=====================
	def uploadImageInformation(self, imagearray, newimagepath, dims, seriescount, numinseries, nframes):
		### setup scope data
		if not self.preset_image:
			scopedata = leginon.leginondata.ScopeEMData()
			scopedata['session'] = self.sessiondata
			scopedata['tem'] = self.temdata
			scopedata['magnification'] = self.params['magnification']
			scopedata['high tension'] = self.params['kv']*1000
		else:
			scopedata = leginon.leginondata.ScopeEMData(initializer=self.preset_image['scope'])
			# update system time to now so they are shown in order of upload.
			scopedata['system time'] = time.time()
		### these are dynamic variables
		scopedata['defocus'] = self.getImageDefocus(numinseries)
		scopedata['stage position'] = {
			'x': 0.0,
			'y': 0.0,
			'z': 0.0,
			'a': self.getTiltAngle(numinseries),
		}
		if self.params['uploadtype'] == "tiltseries":
			scopedata['stage position']['phi'] = self.params['azimuth']

		### setup camera data
		if not self.preset_image:
			cameradata = leginon.leginondata.CameraEMData()
			cameradata['binning'] = {'x': 1, 'y': 1}
			cameradata['frame time'] = 100.0
		else:
			cameradata = leginon.leginondata.CameraEMData(initializer=self.preset_image['camera'])
		cameradata['session'] = self.sessiondata
		cameradata['ccdcamera'] = self.camdata
		cameradata['dimension'] = dims
		cameradata['save frames'] = (nframes > 1)
		cameradata['nframes'] = nframes
		if cameradata['frame time']:
			cameradata['exposure time'] = cameradata['frame time'] * nframes

		### setup camera data
		if self.preset_image and self.preset_image['preset']:
			presetdata = leginon.leginondata.PresetData(initializer=self.preset_image['preset'])
		else:
			presetdata = leginon.leginondata.PresetData()
		presetdata['session'] = self.sessiondata
		presetdata['tem'] = self.temdata
		presetdata['ccdcamera'] = self.camdata
		if not self.preset_image:
			presetdata['magnification'] = self.params['magnification']
		else:
			presetdata['magnification'] = self.preset_image['scope']['magnification']

		try:
			self.params['doseliststr']
			presetdata['dose'] = self.getDose(numinseries)*(10**20)
		except:
			pass

		presetname = 'upload'
		# defocal series have different preset for each member
		if self.params['uploadtype'] == "defocalseries":
			presetname += '%d' %(numinseries)
		presetdata['name'] = presetname

		### setup image data
		imgdata = leginon.leginondata.AcquisitionImageData()
		imgdata['session'] = self.sessiondata
		imgdata['scope'] = scopedata
		imgdata['camera'] = cameradata
		imgdata['preset'] = presetdata
		basename = os.path.basename(newimagepath)
		if basename.endswith(".mrc"):
			basename = os.path.splitext(basename)[0]
		imgdata['filename'] = basename
		imgdata['label'] = 'UploadImage'

		### use real imagearray to ensure that file is saved before database insert
		imgdata['image'] = imagearray

		if self.params['target_parent']:
			parentimage = leginon.leginondata.AcquisitionImageData().direct_query(self.params['target_parent'])
			imgdata['target'] = self.linkTargetParent(parentimage)
		else:
			### use this for defocal group data
			imgdata['target'] = self.setDefocalTargetData(seriescount)

		### use this for tilt series data
		imgdata['tilt series'] = self.getTiltSeries(seriescount)

		# references
		for key in list(self.refdata.keys()):
			imgdata[key] = self.refdata[key]

		if self.params['commit'] is True:
			imgdata.insert()

	#=====================
	def updatePixelSizeCalibration(self):
		"""
		This updates the pixel size for the magnification on the
		instruments before the image is published.  Later query will look up the
		pixelsize calibration closest and before the published image 
		"""
		if self.preset_image:
			# no need to update
			apDisplay.printWarning('Using preset image pixel size')
			return False
		pixelcalibrationq = leginon.leginondata.PixelSizeCalibrationData()
		pixelcalibrationq['magnification'] = self.params['magnification']
		pixelcalibrationq['tem'] = self.temdata
		pixelcalibrationq['ccdcamera'] = self.camdata
		pixelcalibrationdatas = pixelcalibrationq.query(results=1)
		if pixelcalibrationdatas:
			lastpixelsize = pixelcalibrationdatas[0]['pixelsize']
			if self.params['mpix'] == lastpixelsize:
				if pixelcalibrationq['session'] is not None:
					lastsession = pixelcalibrationq['session']['name']
					if lastsession == self.params['sessionname']:
						### values have been set correctly already
						return False

		pixelcalibrationq['pixelsize'] = self.params['mpix']
		pixelcalibrationq['comment'] = 'based on uploaded pixel size'
		pixelcalibrationq['session'] = self.sessiondata

		if self.params['commit'] is True:
			pixelcalibrationq.insert()

	#=====================
	def newImagePath(self, mrcfile, numinseries):
		'''
		Returns full path for uploaded image and frames
		'''
		extension = os.path.splitext(mrcfile)[1]
		# input may be an absolute path or local filename
		rootname = os.path.splitext(os.path.basename(mrcfile))[0]
		# handle name containing .frames
		if rootname.endswith('.frames'):
			rootname = rootname[:-7]
		newroot = rootname+"_"+str(numinseries)
		if not newroot.startswith(self.params['sessionname']):
			newroot = self.params['sessionname']+"_"+newroot
		# image file name is always mrc
		newname = newroot+'.mrc'
		# frame name includes .frames and the original extension
		newframename = newroot+'.frames'+extension
		newimagepath = os.path.join(self.leginonimagedir, newname)
		newframepath = os.path.join(self.leginonframedir, newframename)
		return newimagepath, newframepath

	#=====================
	def readFile(self, oldmrcfile):
		apDisplay.printMsg('Reading %s into memory' % oldmrcfile)
		imagearray = mrc.read(oldmrcfile)
		# invert image density
		if self.params['invert'] is True:
			imagearray *= -1.0
		return imagearray

	#=====================
	def getImageDimensions(self, mrcfile):
		'''
		Returns dictionary of x,y dimension for an mrc or tif image/image stack
		'''
		if self.getFileFormat(mrcfile) == 'mrc':
			return self._getMrcImageDimensions(mrcfile)
		else:
			return self._getTifImageDimensions(mrcfile)

	def _getMrcImageDimensions(self, mrcfile):
		mrcheader = mrc.readHeaderFromFile(mrcfile)
		x = int(mrcheader['nx'].astype(numpy.uint16))
		y = int(mrcheader['ny'].astype(numpy.uint16))
		return {'x': x, 'y': y}

	def _getTifImageDimensions(self, tiffile):
		info = numpil.readInfo(tiffile)
		return {'x':info['nx'],'y':info['ny']}

	def getNumberOfFrames(self, mrcfile):
		'''
		Returns number of frames of an mrc or tif image/image stack
		'''
		if self.getFileFormat(mrcfile) == 'mrc':
			return self._getMrcNumberOfFrames(mrcfile)
		else:
			return self._getTifNumberOfFrames(mrcfile)

	def _getMrcNumberOfFrames(self, mrcfile):
		mrcheader = mrc.readHeaderFromFile(mrcfile)
		return max(1,int(mrcheader['nz'].astype(numpy.uint16)))

	def _getTifNumberOfFrames(self, tiffile):
		info = numpil.readInfo(tiffile)
		return max(1,info['nz'])

	def makeFrameDir(self,newdir):
		fileutil.mkdirs(newdir)

	def copyFrames(self,source,destination):
		apFile.safeCopy(source, destination)
		
	def unstack(self,mrc_stack):
		apDisplay.printMsg("Unstacking mrc stack. A temporary extraction directory will be made using the stack name prefix.")
		prefix = os.path.splitext(os.path.basename(mrc_stack))[0]
		stack_path = os.path.dirname(os.path.abspath(mrc_stack))
		temp_image_dir = "%s/%s_tmp" % (stack_path, prefix)
		os.system('mkdir %s 2>/dev/null' % temp_image_dir)
		# Only for mrc
		stack = mrc.read(mrc_stack)
		for tilt_image in range(1,len(stack)+1):
			mrc.write(stack[tilt_image-1],"%s/%s_%04d.mrc" % (temp_image_dir, prefix, tilt_image))
		return temp_image_dir
		
	def prepareImageForUpload(self,origfilepath,newframepath=None,nframes=1):	
		### In order to obey the rule of first save image then insert 
		### database record, image need to be read as numpy array, not copied
		### single image should not overload memory
		apDisplay.printMsg("Reading original image: "+origfilepath)
		input_format = self.getFileFormat(origfilepath)
		if nframes <= 1:
			if input_format == 'mrc':
				imagearray = mrc.read(origfilepath)
			elif input_format == 'tif':
				imagearray = numpil.read(origfilepath)
		else:
			apDisplay.printMsg('Summing %d frames for image upload' % nframes)
			if input_format == 'mrc':
				imagearray = mrc.sumStack(origfilepath)
			elif input_format == 'tif':
				imagearray = numpil.sumTiffStack(origfilepath)
			else:
				apDisplay.printError('Do not know how to handle %s' % (input_format,))
			apDisplay.printMsg('Copying frame stack %s to %s' % (origfilepath,newframepath))
			self.copyFrames(origfilepath,newframepath)
		return imagearray

	def uploadRefImage(self,reftype,refpath):
		if refpath is None:
			nframes = 1
			if reftype == 'dark':
				imagearray = numpy.zeros((self.dims['y'],self.dims['x']))
			else:
				apDisplay.printError('It is only o.k. to fake dark reference')
		else:
			nframes = self.getNumberOfFrames(refpath)
			imagearray = self.prepareImageForUpload(refpath,None,nframes)
		scopedata = self.makeScopeEMData()
		cameradata = self.makeCameraEMData(dimension=self.dims,nframes=nframes)
		imagedata = {'image':imagearray,'scope':scopedata,'camera':cameradata}	
		self.refdata[reftype] = self.c_client.storeCorrectorImageData(imagedata, reftype, 0)

	def correctImage(self,rawarray,nframes):
		if 'norm' in list(self.refdata.keys()) and self.refdata['norm']:
			normarray = self.refdata['norm']['image']
			if 'dark' in list(self.refdata.keys()) and self.refdata['dark']:
				darkarray = self.refdata['dark']['image']*nframes/self.refdata['dark']['camera']['nframes']
			else:
				darkarray = numpy.zeros(rawarray.shape)
			apDisplay.printMsg('Normalizing image before upload')
			return self.c_client.normalizeImageArray(rawarray, darkarray, normarray)
		else:
			# no norm/dark to correct
			return rawarray

	def startInit(self):
		"""
		Initialization of variables
		"""
		# reference data for gain/dark correction
		self.refdata = {}
		# imagedata to base scope and camera data on
		self.setPresetImage()
		### try and get the appion instruments unless base_preset is set
		self.setInstruments()
		### create new session or set old session,
		self.setSession()
		# For gain/dark corrections
		self.c_client = apDBImage.ApCorrectorClient(self.sessiondata,True)

	#=====================
	def start(self):
		"""
		This is the core of your function.
		You decide what happens here!
		"""
		self.startInit()

		if self.params['normimg']:
			# need at least normimg to upload reference. darkimg can be faked
			self.dims = self.getImageDimensions(self.params['normimg'])
			# self.dims is only defined with normimg is present
			self.uploadRefImage('norm', self.params['normimg'])
			self.uploadRefImage('dark', self.params['darkimg'])
		if os.path.isfile(self.params['imagedir']):
			temp_image_dir = self.unstack(self.params['imagedir'])
			mrclist = self.getImagesInDirectory(temp_image_dir)
		else:
			mrclist = self.getImagesInDirectory(self.params['imagedir'])

		for i in range(min(len(mrclist),6)):
			print(mrclist[i])

		numinseries = 1
		seriescount = 1
		count = 1
		t0 = time.time()
		for mrcfile in mrclist:
			if not os.path.isfile(mrcfile):
				continue
			### rename image
			newimagepath, newframepath = self.newImagePath(mrcfile, numinseries)
			### get image dimensions
			dims = self.getImageDimensions(mrcfile)
			nframes = self.getNumberOfFrames(mrcfile)
			if nframes > 1:
				self.makeFrameDir(self.leginonframedir)
			### set pixel size in database
			self.updatePixelSizeCalibration()

			## read the image/summed file into memory and copy frames if available
			imagearray = self.prepareImageForUpload(mrcfile,newframepath,nframes)

			## do gain/dark correction if needed
			imagearray = self.correctImage(imagearray,nframes)

			### upload image
			self.uploadImageInformation(imagearray, newimagepath, dims, seriescount, numinseries, nframes)

			### counting
			numinseries += 1
			if numinseries % (self.params['seriessize']+1) == 0:
				### reset series counter
				seriescount += 1
				numinseries = 1

			#print count, seriescount, numinseries
			timeperimage = (time.time()-t0)/float(count)
			apDisplay.printMsg("time per image: %s"
				%(apDisplay.timeString(timeperimage)))
			esttime = timeperimage*(len(mrclist) - count)
			apDisplay.printMsg("estimated time remaining for %d of %d images: %s"
				%(len(mrclist)-count, len(mrclist), apDisplay.timeString(esttime)))
			### counting
			count += 1
		
		if os.path.isfile(self.params['imagedir']):
			shutil.rmtree(temp_image_dir)

#=====================
#=====================
if __name__ == '__main__':
	upimages = UploadImages()
	upimages.start()
	upimages.close()

