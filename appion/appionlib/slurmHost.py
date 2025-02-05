import processingHost
import subprocess

# dcshrum@fsu.edu
class SlurmHost(processingHost.ProcessingHost):
	def __init__ (self, command, jobType, configDict=None):
            
		# added so detail on what kind of job is available in the class
		# for web service that generates headers.  The plan is for this custom class to go away :)
		# dcshrum@fsu.edu
		self.command = command
		self.jobType = jobType
        
		processingHost.ProcessingHost.__init__(self)  #initialize parent
		self.type="Slurm"
		self.execCommand="sbatch"
		self.statusCommand="squeue"
		self.scriptPrefix="#SBATCH"
		if configDict:
				self.configure(configDict)
                # print "SlurmHost object created\n"            
                            
                

	##generateHeaders (jobObject)
	#Takes a job object or no arguments. If jobObject is supplied it uses it to 
	#construct processing host specific resource directives.  If no argument is
	#supplied used the currentJob property set in the class instance.		 
	def generateHeaders(self, jobObject=None):
		if jobObject != None:
			currentJob=jobObject
		elif self.currentJob != None:
			currentJob=self.currentJob
		else:
			raise UnboundLocalError ("Current Job not set")
               
             
		#Every Shell Script starts by indicating shell type
		header = "#!" + self.getShell() + "\n"
			   
		#add job attribute headers
		if currentJob.getWalltime():
			header += self.scriptPrefix +" -t " + str(currentJob.getWalltime())+":00:00\n"
                        
		if currentJob.getNodes():
			header += self.scriptPrefix +" -N " + str(currentJob.getNodes())
			header += "\n"
		
		if currentJob.getMem():
			header += self.scriptPrefix +" --mem=" + str(currentJob.getMem()) + 'gb\n'
		
		if currentJob.getPmem():
			header += self.scriptPrefix +" --mem-per-cpu=" + str(currentJob.getPmem()) + "M\n"
			
		if currentJob.getQueue():
			header += self.scriptPrefix +" -p " + currentJob.getQueue() + "\n"
			
		if currentJob.getAccount():
			header += self.scriptPrefix +" -A " + currentJob.getAccount()+ "\n"
			
		#Add any custom headers for this processing host.
		for line in self.getAdditionalHeaders():
			header += self.scriptPrefix + " " + line + "\n"			   
		#add some white space	  
		if self.preExecLines:	 
			header += "\n\n"
		#Add any custom line that should be added to jobfile (Ex. module purge)
		for line in self.getPreExecutionLines():
			header += line + "\n"
		#add some white space  
		header += "\n\n"
		return header
	
	#translateOutput (outputString)
	#Takes the outputSring returned by executing a command (executeCommand()) and
	#Translates it into a Job ID which can be used to check job status.	 This is 
	#fairly simple for Torque since the output of qsub should be a job id of the form
	# <id#.servername.domain>
	def translateOutput (self, outputString):
		outputList = outputString.split(' ')
		try:
			jobID= int(outputList[3])
		except Exception:
			return False
		return jobID	  
		
	
	def checkJobStatus(self, procHostJobId):
		statusCommand = self.getStatusCommand() + " -h -o '%t' -j " + str(procHostJobId)
		
		try:
			process = subprocess.Popen(statusCommand, 
										stdout=subprocess.PIPE, 
										stderr=subprocess.PIPE, 
										shell=True)
			returnCode=process.wait()
			
			if returnCode != 0:
				#return unknown status if check resulted in a error
				return 'U'
			else:
				rstring = process.communicate()[0]
				status =  rstring.split('\n')[2].split()[4]
				#translate torque status codes to appion codes
				if status == 'CG':
					#Job completed of is exiting
					return 'D'
				elif status == 'R':
					#Job is running
					return 'R'
				else:
					#Interpret everything else as queued
					return 'Q'
				
		except Exception:
			return  'U'
