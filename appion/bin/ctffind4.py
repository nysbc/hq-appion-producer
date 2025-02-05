#!/usr/bin/env python

#pythonlib
import os
import re
import math
import time
import shutil
import subprocess
#appion
from appionlib import apFile
from appionlib import apImage
from appionlib import apParam
from appionlib import apDisplay
from appionlib import apDatabase
from appionlib import appiondata
from appionlib import appionLoop2
from appionlib import apInstrument
from appionlib import apDDprocess
from appionlib.apCtf import ctfdb
from appionlib.apCtf import ctfinsert
from appionlib.apCtf import ctffind4AvgRotPlot
import stat
import getpass
from time import sleep
from multiprocessing import Pool

class ctfEstimateLoop(appionLoop2.AppionLoop):
	"""
	appion Loop function that
	CTFFIND 4 was written by Alexis Rohou.
	Appion is Compatible with CTFFIND version 4.1.5
	http://emg.nysbc.org/redmine/projects/appion/wiki/Package_executable_alias_name_in_Appion
	to estimate the CTF in images
	"""

	#======================
	def setupParserOptions(self):
		self.parser.add_option("--ampcontrast", dest="ampcontrast", type="float", default=0.07,
			help="ampcontrast, default=0.07", metavar="#")
		self.parser.add_option("--fieldsize", dest="fieldsize", type="int", default=1024,
			help="fieldsize, default=1024", metavar="#")
		self.parser.add_option("--nominal", dest="nominal", type="float",
			help="nominal override value (in microns, absolute value)")
		self.parser.add_option("--resmin", dest="resmin", type="float", default=50.0,
			help="Low resolution end of data to be fitted in Angstroms", metavar="#")
		self.parser.add_option("--resmax", dest="resmax", type="float", default=15.0,
			help="High resolution end of data to be fitted in Angstroms", metavar="#")
		self.parser.add_option("--defstep", dest="defstep", type="float", default=1000.0,
			help="Step width for grid search in microns", metavar="#")
		self.parser.add_option("--numstep", dest="numstep", type="int", default=25,
			help="Number of steps to search in grid", metavar="#")
		self.parser.add_option("--dast", dest="dast", type="float", default=100.0,
			help="dAst in microns is used to restrain the amount of astigmatism", metavar="#")
		self.parser.add_option("--minphaseshift", "--min_phase_shift", dest="min_phase_shift", type="float", default=10.0,
			help="Minimum phase shift by phase plate, in degrees", metavar="#")
		self.parser.add_option("--maxphaseshift", "--max_phase_shift", dest="max_phase_shift", type="float", default=170.0,
			help="Maximum phase shift by phase plate, in degrees", metavar="#")
		self.parser.add_option("--phasestep", "--phase_search_step", dest="phase_search_step", type="float", default=10.0,
			help="phase shift search step, in degrees", metavar="#")
		self.parser.add_option("--ddstackid", dest="ddstackid",type="int",
			help="DD stack ID", metavar="#")
		self.parser.add_option("--num_frame_avg", dest="num_frame_avg", type="int",default=7,
				help="Average number of moive frames for movie stack CTF refinement")


		## true/false
		self.parser.add_option("--bestdb", "--best-database", dest="bestdb", default=False,
			action="store_true", help="Use best amplitude contrast and astig difference from database")
		self.parser.add_option("--phaseplate", "--phase_plate", dest="shift_phase", default=False,
			action="store_true", help="Find additionalphase shift")
		self.parser.add_option("--exhaust", "--exhaustive-search", dest="exhaustiveSearch", default=False,
			action="store_true", help="Conduct an exhaustive search of the astigmatism of the CTF")
		
	#======================
	def checkConflicts(self):
		if self.params['resmin'] > 50.0:
			apDisplay.printError("Please choose a higher resolution for resmin must be btw 10 and 50")
		if self.params['resmin'] < 10.0:
			apDisplay.printError("Please choose a lower resolution for resmin")
		if self.params['resmax'] > 15.0 or self.params['resmax'] > self.params['resmin']:
			apDisplay.printError("Please choose a higher resolution for resmax")
		if self.params['defstep'] < 0.0001 or self.params['defstep'] > 2.0:
			apDisplay.printError("Please keep the defstep between 0.0001 & 2 microns")
		### set cs value
		self.params['cs'] = apInstrument.getCsValueFromSession(self.getSessionData())
		self.params['is_movie'] = bool(self.params['ddstackid'])
		return


	#======================
	def setProcessingDirName(self):
		self.processdirname = "ctf"

	#======================
	def preLoopFunctions(self):
		self.ctfrun = None
		self.powerspecdir = os.path.join(self.params['rundir'], "opimages")
		if not os.path.isdir(self.powerspecdir):
			apParam.createDirectory(self.powerspecdir, warning=False)
		self.logdir = os.path.join(self.params['rundir'], "logfiles")
		if not os.path.exists(self.logdir):
			apParam.createDirectory(self.logdir, warning=False)
		self.ctfprgmexe = self.getCtfProgPath()
		# check and process more often because it is slower than data collection
		self.setWaitSleepMin(1)
		self.setProcessBatchCount(1)
		return

	#======================
	def getCtfProgPath(self):
		return os.getenv("APPION_CTFFIND4_PATH", "/common/sw/containers/opt/ctffind4/4.1.14/bin/ctffind4")

	#======================
	def postLoopFunctions(self):
		ctfdb.printCtfSummary(self.params, self.imgtree)

	#======================
	def reprocessImage(self, imgdata):
		"""
		Returns
		True, if an image should be reprocessed
		False, if an image was processed and should NOT be reprocessed
		None, if image has not yet been processed
		e.g. a confidence less than 80%
		"""
		if self.params['reprocess'] is None:
			return None
		ctfvalue, conf = ctfdb.getBestCtfValueForImage(imgdata)
		if ctfvalue is None:
			return None
		if conf > self.params['reprocess']:
			return False
		else:
			return True

	def getPhaseParamValue(self):
		return self.getYesNoParamValue('shift_phase')

	def getYesNoParamValue(self, key):
		phaseparam = 'no'
		if self.params[key]:
			phaseparam = 'yes'
		return phaseparam

	def getKnownAstigValue(self):
		return 'no'

	def getExhaustiveAstigSearchValue(self):
		if self.params['exhaustiveSearch'] is True:
			return 'yes'
		return 'no'

	def getRestrainAstigValue(self):
		return 'yes'

	#======================
	def processImage(self, imgdata):

		#get Defocus in Angstroms
		self.ctfvalues = {}
		if self.params['nominal'] is not None:
			print self.params['nominal']
			nominal = abs(self.params['nominal']*1e4)
			apDisplay.printWarning("overriding CTF value with user nominal value %.1f A"%(nominal))
			ctfvalue = None
			bestdef = nominal
		else:
			nominal = abs(imgdata['scope']['defocus']*-1.0e10)
			ctfvalue = ctfdb.getBestCtfByResolution(imgdata)
			if ctfvalue is not None:
				"""
				## CTFFIND V3.5 (7-March-2012) prefers the smaller of the two values for astigmatic images
				I found that say you have an image with 1.1um and 1.5um defocus astigmatism. If you give 
				CTFFIND the average value of 1.3um for the defocus and 0.4um astig (dast) then it will 
				try to fit 1.3um and 1.8um, so you need to give it the minimum value (1.1um) for it to 
				fit 1.1um and 1.5um.
				"""
				bestdef = min(ctfvalue['defocus1'],ctfvalue['defocus2'])*1.0e10
			else:
				bestdef = nominal
		if ctfvalue is not None and self.params['bestdb'] is True:
			if ctfvalue['amplitude_contrast'] > 0:
				bestampcontrast = round(ctfvalue['amplitude_contrast'],3)
			else:
				bestampcontrast = self.params['ampcontrast']
			beststigdiff = round(abs(ctfvalue['defocus1'] - ctfvalue['defocus2'])*1e10,1)
			if beststigdiff < 10:
				#fit is astigmatic, still allow stig
				beststigdiff = self.params['dast']*10000.
		else:
			bestampcontrast = self.params['ampcontrast']
			beststigdiff = self.params['dast']*10000.

		imageresmax = self.params['resmax']
		if ctfvalue is not None and self.params['bestdb'] is True:
			### set res max from resolution_80_percent
			try:
				gmean = (ctfvalue['resolution_80_percent']*ctfvalue['resolution_50_percent']*self.params['resmax'])**(1/3.)
			except:
				gmean = 9999
			if gmean < self.params['resmin']*0.9:
				# replace only if valid Issue #3291
				imageresmax = round(gmean,2)
				apDisplay.printColor("Setting resmax to the geometric mean of resolution values", "purple")

		# dstep is the physical detector pixel size
		apix = apDatabase.getPixelSize(imgdata)

		# may be gain/dark corrected movie that has been binned
		origpath, binning = self.getOriginalPathAndBinning(imgdata)
		# ddstack might be binned.
		apix *= binning

		# inputparams defocii and astig are in Angstroms
		inputparams = {
			'input': apDisplay.short(imgdata['filename'])+".mrc",
			'is_movie': self.getYesNoParamValue('is_movie'),
			'num_frame_avg': self.params['num_frame_avg'],
			'output': apDisplay.short(imgdata['filename'])+"-pow.mrc",
			'apix': apix,
			'kv': imgdata['scope']['high tension']/1000.0,			
			'cs': self.params['cs'],
			'ampcontrast': bestampcontrast,
			'fieldsize': self.params['fieldsize'],
			'resmin': self.params['resmin'],
			'resmax': imageresmax,
			'defmin': None,
			'defmax': None,
			'defstep': self.params['defstep']*10000., #round(defocus/32.0, 1),
			'known_astig': self.getKnownAstigValue(),
			'exhaustive_astig_search': self.getExhaustiveAstigSearchValue(),
			'restrain_astig': self.getRestrainAstigValue(),
			'expect_astig': beststigdiff,
			# For phase plate
			'phase': self.getPhaseParamValue(), # this is a secondary amp contrast term for phase plates
			'min_phase_shift': math.radians(self.params['min_phase_shift']),
			'max_phase_shift': math.radians(self.params['max_phase_shift']), 
			'phase_search_step': math.radians(self.params['phase_search_step']),
			'expert_opts': 'no',
			'newline': '\n',
			# For movie
			'orig': origpath,
		}

		defrange = self.params['defstep'] * self.params['numstep'] * 1e4 ## do 25 steps in either direction # in angstrum
		inputparams['defmin']= round(bestdef-defrange, 1) #in angstrom 
		if inputparams['defmin'] < 0:
			apDisplay.printWarning("Defocus minimum is less than zero")
			inputparams['defmin'] = inputparams['defstep']
		inputparams['defmax']= round(bestdef+defrange, 1) #in angstrom
		apDisplay.printColor("Defocus search range: %d A to %d A (%.2f to %.2f um)"
			%(inputparams['defmin'], inputparams['defmax'], 
			inputparams['defmin']*1e-4, inputparams['defmax']*1e-4), "cyan")

		### secondary lock check right before it starts on the real part
		if self.params['parallel'] and os.path.isfile(apDisplay.short(imgdata['filename'])+".mrc"):
			# This is a secondary image lock check, checking the first output of the process.
			# It alone is not good enough
			apDisplay.printWarning('Some other parallel process is working on the same image. Skipping')
			return
		### create local link to image
		if not os.path.exists(inputparams['input']):
			try:
				os.symlink(inputparams['orig'], inputparams['input'])
			except OSError:
				pass

		if os.path.isfile(inputparams['output']):
			# program crashes if this file exists
			apFile.removeFile(inputparams['output'])

		prompts={
			'Input image file name': os.path.abspath(inputparams['input']),
			'Input is a movie (stack of frames)' : inputparams['is_movie'],
			'Number of frames to average together' : inputparams['num_frame_avg'],
			'Output diagnostic image file name' : os.path.abspath(inputparams['output']),
			'Pixel size' : inputparams['apix'],
			'Acceleration voltage' : inputparams['kv'],
			'Spherical aberration' : inputparams['cs'],
			'Amplitude contrast' : inputparams['ampcontrast'],
			'Size of amplitude spectrum to compute' : inputparams['fieldsize'],
			'Minimum resolution' : inputparams['resmin'],
			'Maximum resolution' : inputparams['resmax'],
			'Minimum defocus' : inputparams['defmin'],
			'Maximum defocus' : inputparams['defmax'],
			'Defocus search step' : inputparams['defstep'],
			'Do you know what astigmatism is present?' : inputparams['known_astig'],
			'Slower, more exhaustive search?' : inputparams['exhaustive_astig_search'],
			'Known astigmatism' : '0.0',
			'Known astigmatism angle': '0.0',
			'Use a restraint on astigmatism?' :inputparams['restrain_astig'],
			'Expected (tolerated) astigmatism': inputparams['expect_astig'],
			'Find additional phase shift?' : inputparams['phase'],
			'Minimum phase shift (rad)' : inputparams['min_phase_shift'],
			'Maximum phase shift (rad)' : inputparams['max_phase_shift'],
			'Phase shift search step' : inputparams['phase_search_step'],
			'Do you want to set expert options?' : inputparams['expert_opts']
		}

		#TODO Render this using a jinja template?
		expectscript=imgdata['filename']+"_ctffind4.exp"
		with open(expectscript, "w") as f:
			f.write("set timeout 10\n\n")
			f.write("spawn %s\n\n" % self.ctfprgmexe)
			f.write("while 1 {\n")
			f.write("\texpect {\n")
			for k,v in prompts.items():
				f.write("\t\t\"%s\" { send \"%s\\n\" }\n" % (k, str(v)))
			f.write("\t\teof {exit 0}\n")
			f.write("\t}\n")
			f.write("}")
		os.chmod(expectscript, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)

		serverdir=os.path.join(self.params['rundir'],"hq","server")
		jobdir=os.path.join(self.params['rundir'],"hq","jobs")
		try:
			if not os.path.exists(serverdir):
				os.makedirs(serverdir)
		except OSError:
			pass
		try:
			if not os.path.exists(jobdir):
				os.makedirs(jobdir)
		except OSError:
			pass
		cmd = "hq --server-dir %s submit --cwd %s --wait --max-fails 3 --time-limit=5min --cpus 2 /usr/bin/expect %s" % (os.getenv("HQ_SERVER_DIR",serverdir), os.getenv("HQ_CWD", jobdir), os.path.abspath(expectscript))
		#Handles case where command fails because hq server has gone away.
		success=False
		while not success:
			ctfprogproc = subprocess.Popen(cmd, shell=True)
			ctfprogproc.wait()
			if ctfprogproc.returncode == 0:
				success=True
			else:
				sleep(15)

		### cannot run ctffind_plot_results.sh on CentOS 6
		# This script requires gnuplot version >= 4.6, but you have version 4.2

		### parse ctf estimation output
		self.ctfvalues = {}
		ctfproglog = apDisplay.short(imgdata['filename'])+"-pow.txt"		
		apDisplay.printMsg("reading %s"%(ctfproglog))
		try:
			logf = open(ctfproglog, "r")
		except:
			apDisplay.printWarning("Error reading %s"%(ctfproglog))
			self.setBadImage(imgdata)
			return
		for line in logf:
			sline = line.strip()
			if sline.startswith('#'):
				continue
			bits = sline.split()
			if len(bits) < 7:
				apDisplay.printWarning("Invalid content in %s"%(ctfproglog))
				self.setBadImage(imgdata)
				return

			self.ctfvalues = {
				'imagenum': int(float(bits[0])),
				'defocus2':	float(bits[1])*1e-10,
				'defocus1':	float(bits[2])*1e-10,
				'angle_astigmatism':	float(bits[3])+90, # see bug #4047 for astig conversion
				'extra_phase_shift':	float(bits[4]), # radians
				'amplitude_contrast': inputparams['ampcontrast'],
				'cross_correlation':	float(bits[5]),
				'ctffind4_resolution':	self.convertCtffind4Resolution(bits[6]),
				'defocusinit':	bestdef*1e-10,
				'cs': self.params['cs'],
				'volts': imgdata['scope']['high tension'],
				'confidence': float(bits[5]),
				'confidence_d': round(math.sqrt(abs(float(bits[5]))), 5)
			}

		if len(self.ctfvalues.keys()) == 0:
			apDisplay.printWarning("Invalid %s"%(ctfproglog))
			self.setBadImage(imgdata)
			return

		#convert powerspectra to JPEG
		outputjpgbase = apDisplay.short(imgdata['filename'])+"-pow.jpg"
		self.lastjpg = outputjpgbase
		outputjpg = os.path.join(self.powerspecdir, self.lastjpg)
		powspec = apImage.mrcToArray(inputparams['output'])
		apImage.arrayToJpeg(powspec, outputjpg)
		shutil.move(inputparams['output'], os.path.join(self.powerspecdir, inputparams['output']))
		self.ctfvalues['graph1'] = outputjpg

		##convert avgrot file to a PNG
		avgrotfile = apDisplay.short(imgdata['filename'])+"-pow_avrot.txt"
		outputpng = ctffind4AvgRotPlot.createPlot(avgrotfile)
		shutil.move(outputpng, os.path.join(self.powerspecdir, outputpng))
		self.ctfvalues['graph2'] = outputpng
		
		#apFile.removeFile(inputparams['input'])

		return

	def convertCtffind4Resolution(self,res_str):
		res_float = float(res_str)
		# ctffind4 output inf if not well fitted
		if res_float == float('inf'):
			# return a number as database can not take inf
			return 100000.0
		return res_float

	#======================
	def commitToDatabase(self, imgdata):
		self.insertCtfRun(imgdata)
		ctfinsert.validateAndInsertCTFData(imgdata, self.ctfvalues, self.ctfrun, self.params['rundir'])

	#======================
	def insertCtfRun(self, imgdata):
		if isinstance(self.ctfrun, appiondata.ApAceRunData):
			return False

		# first create an aceparam object
		paramq = appiondata.ApCtfFind4ParamsData()
		copyparamlist = ['ampcontrast','fieldsize','cs','bestdb','resmin','defstep','shift_phase']
		if self.params['shift_phase']:
			copyparamlist.extend(['min_phase_shift','max_phase_shift','phase_search_step'])
		for p in copyparamlist:
			if p in self.params:
				paramq[p] = self.params[p]

		# create an acerun object
		runq = appiondata.ApAceRunData()
		runq['name'] = self.params['runname']
		runq['session'] = imgdata['session'];

		# see if acerun already exists in the database
		runnames = runq.query(results=1)

		if (runnames):
			prevrun = runnames[0]
			if not (prevrun['ctffind4_params'] == paramq):
				for i in prevrun['ctffind4_params']:
					if prevrun['ctffind4_params'][i] != paramq[i]:
						# float value such as cs of 4.1 is not quite equal
						if type(paramq[i]) == type(1.0) and abs(prevrun['ctffind4_params'][i]-paramq[i]) < 0.00001:
							continue
						apDisplay.printWarning("the value for parameter '"+str(i)+"' is different from before")
						apDisplay.printError("All parameters for a single CTF estimation run must be identical! \n"+\
						     "please check your parameter settings.")
			self.ctfrun = prevrun
			return False

		#create path
		runq['path'] = appiondata.ApPathData(path=os.path.abspath(self.params['rundir']))
		runq['hidden'] = False
		# if no run entry exists, insert new run entry into db
		runq['ctffind4_params'] = paramq
		runq.insert()
		self.ctfrun = runq
		return True

	def getOriginalPathAndBinning(self,imgdata):
		if self.params['ddstackid'] is None:
			origPath = os.path.join(imgdata['session']['image path'], imgdata['filename']+".mrc")
			binning = 1
		else:
			self.dd = apDDprocess.DDStackProcessing()
			self.dd.setDDStackRun(self.params['ddstackid'])
			self.dd.setImageData(imgdata)
			self.ddstackrun = self.dd.getDDStackRun()
			self.ddstackpath = self.ddstackrun['path']['path']
			if not imgdata['camera']['align frames']:
				# ddstack of the ddstack may be different from the source image
				binning = self.ddstackrun['params']['bin']
				source_imgdata = imgdata
			else:
				# but should be the same as the aligned image
				binning = 1
				pair = self.dd.getAlignImagePairData(self.ddstackrun,False)
				source_imgdata = pair['source']
			origPath = os.path.join(self.ddstackpath,source_imgdata['filename']+"_st.mrc")
		return origPath, binning

def main():
	imgLoop = ctfEstimateLoop()
	imgLoop.run()

if __name__ == '__main__':
	appionProcCount=os.getenv("APPION_PROCESSES", 8)
	appionProcCount=int(appionProcCount)
	p=Pool(appionProcCount)
	for _ in range(appionProcCount):
		p.apply_async(main)
	p.close()
	p.join()


