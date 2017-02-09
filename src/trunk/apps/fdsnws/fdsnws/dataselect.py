################################################################################
# Copyright (C) 2013-2014 by gempa GmbH
#
# FDSNDataSelect -- Implements the fdsnws-dataselect Web service, see
#   http://www.fdsn.org/webservices/
#
# Feature notes:
#   - 'quality' request parameter not implemented (information not available in
#     SeisComP)
#   - 'minimumlength' parameter is not implemented
#   - 'longestonly' parameter is not implemented
#
# Author:  Stephan Herrnkind
# Email:   herrnkind@gempa.de
################################################################################

from twisted.cred import portal
from twisted.web import http, resource, server
from twisted.internet import interfaces, reactor

from zope.interface import implements

from seiscomp3 import Logging
from seiscomp3.Client import Application
from seiscomp3.Core import Array, Record, Time, ValueException
from seiscomp3.IO import RecordInput, RecordStream

from http import HTTP
from request import RequestOptions
import utils

import time
from reqtrack import RequestTrackerDB
from msIndex import SDS
import dateutil.parser

################################################################################
class _DataSelectRequestOptions(RequestOptions):

	MinTime        = Time(0, 1)

	PQuality       = [ 'quality' ]
	PMinimumLength = [ 'minimumlength' ]
	PLongestOnly   = [ 'longestonly' ]

	QualityValues  = [ 'B', 'D', 'M', 'Q', 'R' ]
	OutputFormats  = [ 'miniseed', 'mseed' ]

	POSTParams     = RequestOptions.POSTParams + \
	                 PQuality + PMinimumLength + PLongestOnly


	#---------------------------------------------------------------------------
	def __init__(self, args=None):
		RequestOptions.__init__(self, args)
		self.service = 'fdsnws-dataselect'

		self.quality = self.QualityValues[0]
		self.minimumLength = None
		self.longestOnly = None


	#---------------------------------------------------------------------------
	def _checkTimes(self, realtimeGap):
		maxEndTime = Time(self.accessTime)
		if realtimeGap is not None:
			maxEndTime -= Time(realtimeGap, 0)

		for ro in self.streams:
			# create time if non was specified
			if ro.time is None:
				ro.time = RequestOptions.Time()
			# restrict time to 1970 - now
			if ro.time.start is None or ro.time.start < self.MinTime:
				ro.time.start = self.MinTime
			if ro.time.end is None or ro.time.end > maxEndTime:
				ro.time.end = maxEndTime

		# remove items with start time >= end time
		self.streams = [ x for x in self.streams if x.time.start < x.time.end ]


	#---------------------------------------------------------------------------
	def parse(self):
		# quality (optional), currently not supported
		key, value = self.getFirstValue(self.PQuality)
		if value is not None:
			value = value.upper()
			if value in self.QualityValues:
				self.quality = value
			else:
				self.raiseValueError(key)

		# minimumlength(optional), currently not supported
		self.minimumLength = self.parseFloat(self.PMinimumLength, 0)

		# longestonly (optional), currently not supported
		self.longestOnly = self.parseBool(self.PLongestOnly)

		# generic parameters
		self.parseTime()
		self.parseChannel()
		self.parseOutput()


################################################################################
class _MyRecordStream(object):
	def __init__(self, url):
	        sdsprefix = 'sdsarchive://'

		if url.startswith(sdsprefix):
			self.__sds = SDS(url[len(sdsprefix):])
			self.__tw = []
			self.__rs = None

		else:
			self.__sds = None
			self.__tw = None
			self.__rs = RecordStream.Open(url)

			if self.__rs is None:
				raise Exception("could not open record stream")


	def addStream(self, net, sta, loc, cha, startt, endt):
		if self.__sds:
			self.__tw.append((net, sta, loc, cha, startt, endt))

		else:
			self.__rs.addStream(net, sta, loc, cha, startt, endt)


	def input(self):
		if self.__sds:
			for (net, sta, loc, cha, startt, endt) in self.__tw:
				startt = dateutil.parser.parse(startt.iso()).replace(tzinfo=None)
				endt = dateutil.parser.parse(endt.iso()).replace(tzinfo=None)
				for data in self.__sds.getRawBytes(startt, endt, net, sta, loc, cha):
					if data is not None:
						yield data

		else:
			rsInput = RecordInput(self.__rs, Array.INT, Record.SAVE_RAW)
			eof = False

			while not eof:
				data = []
				size = 1024*1024

				while size > 0:
					try:
						rec = rsInput.next()

					except Exception, e:
						Logging.warning("%s" % str(e))
						eof = True
						break

					if rec is None:
						eof = True
						break

					rawrec = rec.raw().str()
					data.append(rawrec)
					size -= len(rawrec)

				if data:
					yield ''.join(data)


################################################################################
class _WaveformProducer(object):
	implements(interfaces.IPushProducer)

	def __init__(self, req, ro, rs, fileName, tracker):
		self.req = req
		self.ro = ro
		self.it = rs.input()

		self.fileName = fileName
		self.written = 0

		self.tracker = tracker
		self.paused = False
		self.stopped = False
		self.running = False


	def _flush(self, data):
		if not self.paused:
			reactor.callInThread(self._collectData)

		else:
			self.running = False

		if self.written == 0:
			self.req.setHeader('Content-Type', 'application/vnd.fdsn.mseed')
			self.req.setHeader('Content-Disposition', "attachment; " \
					   "filename=%s" % self.fileName)

		self.req.write(data)
		self.written += len(data)


	def _finish(self):
		if self.written == 0:
			msg = "no waveform data found"
			data = HTTP.renderErrorPage(self.req, http.NO_CONTENT, msg, self.ro)
			self.req.write(data)

			if self.tracker:
				self.tracker.volume_status("fdsnws", "NODATA", 0, "")
				self.tracker.request_status("END", "")

		else:
			Logging.debug("%s: returned %i bytes of mseed data" % (
				       self.ro.service, self.written))
			utils.accessLog(self.req, self.ro, http.OK, self.written, None)

			if self.tracker:
				self.tracker.volume_status("fdsnws", "OK", self.written, "")
				self.tracker.request_status("END", "")


		self.req.unregisterProducer()
		self.req.finish()


	def _collectData(self):
		if self.stopped:
			return

		try:
			reactor.callFromThread(self._flush, self.it.next())

		except StopIteration:
			reactor.callFromThread(self._finish)


	def pauseProducing(self):
		self.paused = True


	def resumeProducing(self):
		self.paused = False

		if not self.running:
			self.running = True
			reactor.callInThread(self._collectData)


	def stopProducing(self):
		self.stopped = True



################################################################################
class FDSNDataSelectRealm(object):
	implements(portal.IRealm)

	#---------------------------------------------------------------------------
	def __init__(self, inv, access):
		self.__inv = inv
		self.__access = access

	#---------------------------------------------------------------------------
	def requestAvatar(self, avatarId, mind, *interfaces):
		if resource.IResource in interfaces:
			return (resource.IResource,
				FDSNDataSelect(self.__inv, self.__access,
					{"mail": avatarId}),
				lambda: None)

		raise NotImplementedError()



################################################################################
class FDSNDataSelectAuthRealm(object):
	implements(portal.IRealm)

	#---------------------------------------------------------------------------
	def __init__(self, inv, access, userdb):
		self.__inv = inv
		self.__access = access
		self.__userdb = userdb

	#---------------------------------------------------------------------------
	def requestAvatar(self, avatarId, mind, *interfaces):
		if resource.IResource in interfaces:
			return (resource.IResource,
				FDSNDataSelect(self.__inv, self.__access,
					self.__userdb.getAttributes(avatarId)),
				lambda: None)

		raise NotImplementedError()



################################################################################
class FDSNDataSelect(resource.Resource):

	isLeaf = True

	#---------------------------------------------------------------------------
	def __init__(self, inv, access, user=None):
		resource.Resource.__init__(self)
		self._rsURL = Application.Instance().recordStreamURL()
		self.__inv = inv
		self.__access = access
		self.__user = user


	#---------------------------------------------------------------------------
	def render_GET(self, req):
		# Parse and validate POST parameters
		ro = _DataSelectRequestOptions(req.args)
		ro.userName = self.__user and self.__user.get('mail')
		try:
			ro.parse()
			# the GET operation supports exactly one stream filter
			ro.streams.append(ro)
		except ValueError, e:
			Logging.warning(str(e))
			return HTTP.renderErrorPage(req, http.BAD_REQUEST, str(e), ro)

		return self._processRequest(req, ro)


	#---------------------------------------------------------------------------
	def render_POST(self, req):
		# Parse and validate POST parameters
		ro = _DataSelectRequestOptions()
		ro.userName = self.__user and self.__user.get('mail')
		try:
			ro.parsePOST(req.content)
			ro.parse()
		except ValueError, e:
			Logging.warning(str(e))
			return HTTP.renderErrorPage(req, http.BAD_REQUEST, str(e), ro)

		return self._processRequest(req, ro)


	#-----------------------------------------------------------------------
	def _networkIter(self, ro):
		for i in xrange(self.__inv.networkCount()):
			net = self.__inv.network(i)

			# network code
			if ro.channel and not ro.channel.matchNet(net.code()):
				continue

			# start and end time
			if ro.time:
				try: end = net.end()
				except ValueException: end = None
				if not ro.time.match(net.start(), end):
					continue

			yield net


	#---------------------------------------------------------------------------
	def _stationIter(self, net, ro):
		for i in xrange(net.stationCount()):
			sta = net.station(i)

			# station code
			if ro.channel and not ro.channel.matchSta(sta.code()):
				continue

			# start and end time
			if ro.time:
				try: end = sta.end()
				except ValueException: end = None
				if not ro.time.match(sta.start(), end):
					continue

			yield sta


	#---------------------------------------------------------------------------
	def _locationIter(self, sta, ro):
		for i in xrange(sta.sensorLocationCount()):
			loc = sta.sensorLocation(i)

			# location code
			if ro.channel and not ro.channel.matchLoc(loc.code()):
				continue

			# start and end time
			if ro.time:
				try: end = loc.end()
				except ValueException: end = None
				if not ro.time.match(loc.start(), end):
					continue

			yield loc


	#---------------------------------------------------------------------------
	def _streamIter(self, loc, ro):
		for i in xrange(loc.streamCount()):
			stream = loc.stream(i)

			# stream code
			if ro.channel and not ro.channel.matchCha(stream.code()):
				continue

			# start and end time
			if ro.time:
				try: end = stream.end()
				except ValueException: end = None
				if not ro.time.match(stream.start(), end):
					continue

			yield stream


	#---------------------------------------------------------------------------
	def _processRequest(self, req, ro):

		if ro.quality != 'B' and ro.quality != 'M':
			msg = "quality other than 'B' or 'M' not supported"
			return HTTP.renderErrorPage(req, http.SERVICE_UNAVAILABLE, msg, ro)

		if ro.minimumLength:
			msg = "enforcing of minimum record length not supported"
			return HTTP.renderErrorPage(req, http.SERVICE_UNAVAILABLE, msg, ro)

		if ro.longestOnly:
			msg = "limitation to longest segment not supported"
			return HTTP.renderErrorPage(req, http.SERVICE_UNAVAILABLE, msg, ro)

		app = Application.Instance()
		ro._checkTimes(app._realtimeGap)

		# Open record stream
		try: rs = _MyRecordStream(self._rsURL)
		except Exception, e: return HTTP.renderErrorPage(req, http.SERVICE_UNAVAILABLE, str(e), ro)

		maxSamples = None
		if app._samplesM is not None:
			maxSamples = app._samplesM * 1000000
			samples = 0

		app = Application.Instance()
		if app._trackdbEnabled:
			userid = ro.userName or app._trackdbDefaultUser
			reqid = 'ws' + str(int(round(time.time() * 1000) - 1420070400000))
			tracker = RequestTrackerDB("fdsnws", app.connection(), reqid, "WAVEFORM", userid, "REQUEST WAVEFORM " + reqid, "fdsnws", req.getClientIP(), req.getClientIP())

		else:
			tracker = None

		# Add request streams
		# iterate over inventory networks
		for s in ro.streams:
			for net in self._networkIter(s):
				for sta in self._stationIter(net, s):
					for loc in self._locationIter(sta, s):
						for cha in self._streamIter(loc, s):
							if utils.isRestricted(cha) and (self.__user is None or \
								not self.__access.authorize(self.__user,
											    net.code(),
											    sta.code(),
											    loc.code(),
											    cha.code(),
											    s.time.start,
											    s.time.end)):
								continue

							# enforce maximum sample per request restriction
							if maxSamples is not None:
								try:
									n = cha.sampleRateNumerator()
									d = cha.sampleRateDenominator()
								except ValueException:
									msg = "skipping stream without sampling " \
									      "rate definition: %s.%s.%s.%s" % (
									      net.code(), sta.code(), loc.code(),
									      cha.code())
									Logging.warning(msg)
									continue

								# calculate number of samples for requested
								# time window
								diffSec = (s.time.end - s.time.start).length()
								samples += int(diffSec * n / d)
								if samples > maxSamples:
									msg = "maximum number of %sM samples " \
									      "exceeded" % str(app._samplesM)
									return HTTP.renderErrorPage(req,
									       http.REQUEST_ENTITY_TOO_LARGE, msg,
									       ro)

							Logging.debug("adding stream: %s.%s.%s.%s %s - %s" \
							              % (net.code(), sta.code(), loc.code(),
							                 cha.code(), s.time.start.iso(),
							                 s.time.end.iso()))
							rs.addStream(net.code(), sta.code(), loc.code(),
							             cha.code(), s.time.start, s.time.end)

							if tracker:
								tracker.line_status(s.time.start, s.time.end,
								    net.code(), sta.code(), cha.code(), loc.code(),
								    False, "", True, [], "fdsnws", "OK", 0, "")

		# Build output filename
		fileName = Application.Instance()._fileNamePrefix.replace("%time", time.strftime('%Y-%m-%dT%H:%M:%S'))+'.mseed'

		# Create producer for async IO
		prod = _WaveformProducer(req, ro, rs, fileName, tracker)
		req.registerProducer(prod, True)
		prod.resumeProducing()

		# The request is handled by the deferred object
		return server.NOT_DONE_YET
