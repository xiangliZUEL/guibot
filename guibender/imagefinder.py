# Copyright 2013 Intranet AG / Thomas Jarosch and Plamen Dimitrov
#
# guibender is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# guibender is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with guibender.  If not, see <http://www.gnu.org/licenses/>.
#
import logging
import PIL.Image
from tempfile import NamedTemporaryFile
import math

from location import Location
from cvequalizer import CVEqualizer
from errors import *

from autopy import bitmap
import cv, cv2
import numpy


class ImageFinder:
    """
    The image finder contains all image matching functionality.

    It offers both template matching and feature matching algorithms
    through autopy or through the OpenCV library. The image finding
    methods include: general find, template and feature find, and
    all matches above similarity find.
    """

    def __init__(self, equalizer = None):
        """
        Initiates the image finder and its CV backend equalizer.

        The image logging consists of saving the last hotmap. If the
        template matching method was used, the hotmap is a finger
        print of the matching in the entire haystack. Its lighter
        areas are places where the needle was matched better. If the
        feature matching method was used, the hotmap contains the
        matched needle features in the haystack (green), the ones
        that were not matched (red), and the calculated focus point
        that would be used for clicking, hovering, etc. (blue).
        """
        if equalizer == None:
            self.eq = CVEqualizer()
        else:
            self.eq = equalizer

        # other attributes
        self._bitmapcache = {}
        # 0 NOTSET, 10 DEBUG, 20 INFO, 30 WARNING, 40 ERROR, 50 CRITICAL
        self.image_logging = 20
        # contains the last matched image as a numpy array, the matched
        # similarity and the matched coordinates
        self.hotmap = [None, -1.0, None]

    def find(self, haystack, needle, similarity, nocolor = True):
        """
        Finds an image in another if above some similarity and returns a
        Location() object or None using all default algorithms and parameters.

        This is the most general find method.

        @param haystack: an Image() to look in
        @param needle: an Image() to look for
        @param similarity: a float in the interval [0.0, 1.0] where 1.0
        requires 100% match
        @param nocolor: a bool defining whether to use grayscale images
        """
        if self.eq.current["find"] == "template":
            return self.find_template(haystack, needle, similarity, nocolor)
        elif self.eq.current["find"] == "feature":
            return self.find_features(haystack, needle, similarity)
        else:
            raise ImageFinderMethodError

    def find_template(self, haystack, needle, similarity, nocolor = True):
        """
        Finds a needle image in a haystack image using template matching.

        Returns a Location object for the match or None in not found.

        Available template matching methods are: autopy, opencv
        """
        if self.eq.current["tmatch"] not in self.eq.algorithms["template_matchers"]:
            raise ImageFinderMethodError

        elif self.eq.current["tmatch"] == "autopy":
            if needle.get_filename() in self._bitmapcache:
                autopy_needle = self._bitmapcache[needle.get_filename()]
            else:
                # load and cache it
                # TODO: Use in-memory conversion
                autopy_needle = bitmap.Bitmap.open(needle.get_filename())
                self._bitmapcache[needle.get_filename()] = autopy_needle

            # TODO: Use in-memory conversion
            with NamedTemporaryFile(prefix='guibender', suffix='.png') as f:
                haystack.save(f.name)
                autopy_screenshot = bitmap.Bitmap.open(f.name)

                autopy_tolerance = 1.0 - similarity
                # TODO: since only the coordinates are available
                # and fuzzy areas of matches are returned we need
                # to ask autopy team for returning the matching rates
                # as well
                coord = autopy_screenshot.find_bitmap(autopy_needle, autopy_tolerance)

                if coord is not None:
                    self.hotmap[1] = -1.0
                    self.hotmap[2] = coord
                    return Location(coord[0], coord[1])
            return None

        else:
            result = self._match_template(haystack, needle, nocolor, self.eq.current["tmatch"])

            minVal,maxVal,minLoc,maxLoc = cv2.minMaxLoc(result)
            logging.debug('minVal: %s', str(minVal))
            logging.debug('minLoc: %s', str(minLoc))
            logging.debug('maxVal (similarity): %s (%s)',
                          str(maxVal), similarity)
            logging.debug('maxLoc (x,y): %s', str(maxLoc))
            # switch max and min for sqdiff and sqdiff_normed
            if self.eq.current["tmatch"] in ("sqdiff", "sqdiff_normed"):
                maxVal = 1 - minVal
                maxLoc = minLoc

            # print a hotmap of the results for debugging purposes
            if self.image_logging <= 40:
                # currenly the image showing methods still don't work
                # due to opencv bug
                #cv2.startWindowThread()
                #cv2.namedWindow("test", 1)
                #cv2.imshow("test", match)

                hotmap = cv.CreateMat(len(result), len(result[0]), cv.CV_8UC1)
                cv.ConvertScale(cv.fromarray(result), hotmap, scale = 255.0)
                self.hotmap[0] = numpy.asarray(hotmap)
                cv2.imwrite("log.png", self.hotmap[0])

            if maxVal > similarity:
                self.hotmap[1] = maxVal
                self.hotmap[2] = maxLoc
                return Location(maxLoc[0], maxLoc[1])
            return None

    def find_features(self, haystack, needle, similarity):
        """
        Finds a needle image in a haystack image using feature matching.

        Returns a Location object for the match or None in not found.

        Available methods are: a combination of feature detector,
        extractor, and matcher
        """
        hgray = self._prepare_image(haystack, gray = True)
        ngray = self._prepare_image(needle, gray = True)

        self.hotmap[0] = self._prepare_image(haystack)
        self.hotmap[1] = 0.0
        self.hotmap[2] = None

        hkp, hdc, nkp, ndc = self._detect_features(hgray, ngray,
                                                   self.eq.current["fdetect"],
                                                   self.eq.current["fextract"])

        if len(nkp) < 4 or len(hkp) < 4:
            if self.image_logging <= 40:
                cv2.imwrite("log.png", self.hotmap[0])
            return None

        mhkp, mnkp = self._match_features(hkp, hdc, nkp, ndc,
                                          self.eq.current["fmatch"])

        if self.hotmap[1] < similarity or len(mnkp) < 4:
            if self.image_logging <= 40:
                cv2.imwrite("log.png", self.hotmap[0])
            return None

        self._project_needle_center(needle, mnkp, mhkp)

        if self.image_logging <= 40:
            cv2.imwrite("log.png", self.hotmap[0])
        if self.hotmap[1] < similarity:
            return None
        else:
            return Location(*self.hotmap[2])

    def find_all(self, haystack, needle, similarity, nocolor = True):
        """
        Finds all needle images in a haystack image using template matching.

        Returns a list of Location objects for all matches or None in not found.

        Available template matching methods are: opencv
        """
        if self.eq.current["tmatch"] not in self.eq.algorithms["template_matchers"]:
            raise ImageFinderMethodError

        # autopy template matching for find_all is replaced by ccoeff_normed
        # since it is inefficient and returns match clouds
        if self.eq.current["tmatch"] == "autopy":
            match_template = "ccoeff_normed"
        else:
            match_template = self.eq.current["tmatch"]
        result = self._match_template(haystack, needle, nocolor, match_template)

        # extract maxima once for each needle size region
        maxima = []
        while True:

            minVal,maxVal,minLoc,maxLoc = cv2.minMaxLoc(result)
            # switch max and min for sqdiff and sqdiff_normed
            if self.eq.current["tmatch"] in ("sqdiff", "sqdiff_normed"):
                # TODO: check whetehr find_all would work properly for sqdiff
                maxVal = 1 - minVal
                maxLoc = minLoc
            if maxVal < similarity:
                break

            logging.debug('Found a match with:')
            logging.debug('maxVal (similarity): %s (%s)',
                          str(maxVal), similarity)
            logging.debug('maxLoc (x,y): %s', str(maxLoc))

            maxima.append(Location(maxLoc[0], maxLoc[1]))

            res_w = haystack.width - needle.width + 1
            res_h = haystack.height - needle.height + 1
            match_x0 = max(maxLoc[0] - int(0.5 * needle.width), 0)
            match_x1 = min(maxLoc[0] + int(0.5 * needle.width), res_w)
            match_y0 = max(maxLoc[1] - int(0.5 * needle.height), 0)
            match_y1 = min(maxLoc[1] + int(0.5 * needle.height), len(result[0]))

            logging.debug("Wipe image matches in x [%s, %s]\[%s, %s]",
                          match_x0, match_x1, 0, res_w)
            logging.debug("Wipe image matches in y [%s, %s]\[%s, %s]",
                          match_y0, match_y1, 0, res_h)

            # clean found image to look for next safe distance match
            for i in range(max(maxLoc[0] - int(0.5 * needle.width), 0),
                           min(maxLoc[0] + int(0.5 * needle.width), res_w)):
                for j in range(max(maxLoc[1] - int(0.5 * needle.height), 0),
                               min(maxLoc[1] + int(0.5 * needle.height), res_h)):

                    #print haystack.width, needle.width, maxLoc[0], maxLoc[0] - int(0.5 * needle.width), max(maxLoc[0] - int(0.5 * needle.width), 0)
                    #print haystack.width, needle.width, maxLoc[0], maxLoc[0] + int(0.5 * needle.width), min(maxLoc[0] + int(0.5 * needle.width), 0)
                    #print haystack.height, needle.height, maxLoc[1], maxLoc[1] - int(0.5 * needle.height), max(maxLoc[1] - int(0.5 * needle.height), 0)
                    #print haystack.height, needle.height, maxLoc[1], maxLoc[1] + int(0.5 * needle.height), min(maxLoc[1] + int(0.5 * needle.height), 0)
                    #print "index at ", j, i, " in ", len(result), len(result[0])

                    result[j][i] = 0.0
            logging.debug("Total maxima up to the point are %i", len(maxima))
            logging.debug("maxLoc was %s and is now %s", maxVal, result[maxLoc[1], maxLoc[0]])
        logging.info("%i matches found" % len(maxima))

        # print a hotmap of the results for debugging purposes
        if self.image_logging <= 40:
            hotmap = cv.CreateMat(len(result), len(result[0]), cv.CV_8UC1)
            cv.ConvertScale(cv.fromarray(result), hotmap, scale = 255.0)
            self.hotmap[0] = numpy.asarray(hotmap)
            cv2.imwrite("log.png", self.hotmap[0])
        self.hotmap[1] = maxVal
        self.hotmap[2] = maxLoc

        return maxima

    def find_hybrid(self, haystack, needle, similarity,
                    x = 1000, y = 1000, dx = 100, dy = 100):
        """
        Divide the haystack into x,y subregions and perform feature
        matching once for each dx,dy translation of each subregion.

        This method uses advantages of both template and feature
        matching in order to locate the needle.

        Note: Currently this method is dangerous due to a possible
        memory leak. Therefore avoid getting closer to a more normal
        template matching or any small size and delta (x,y and dx,dy) that
        will cause too many match attempts.

        Examples:
            1) Normal template matching:

                find_hybrid(n, h, s, n.width, n.height, 1, 1)

            2) Divide the screen into four quadrants and jump with distance
            halves of these quadrants:

                find_hybrid(n, h, s, h.width/2, h.height/2, h.width/4, h.height/4)
        """
        hgray = self._prepare_image(haystack, gray = True)
        ngray = self._prepare_image(needle, gray = True)

        # stop image logging since the this search is intensive
        logging = self.image_logging
        self.image_logging = 50

        # the translation distance cannot be larger than the haystack
        dx = min(dx, haystack.width)
        dy = min(dy, haystack.height)
        nx = int(math.ceil(float(max(haystack.width - x, 0)) / dx) + 1)
        ny = int(math.ceil(float(max(haystack.height - y, 0)) / dy) + 1)
        #print "dividing haystack into %ix%i pieces" % (nx, ny)
        result = numpy.zeros((ny, nx))

        self.hotmap[0] = None
        self.hotmap[1] = 0.0
        self.hotmap[2] = None

        locations = {}
        for i in range(nx):
            for j in range(ny):
                left = i * dx
                right = min(haystack.width, i * dx + x)
                up = j * dy
                down = min(haystack.height, j * dy + y)
                #print "up-down:", (up, down), "left-right:", (left, right)
                hregion = hgray[up:down, left:right]
                hregion = hregion.copy()

                # uncomment this block in order to perform image logging
                # for the current haystack subregion into the hotmap
                #self.hotmap[0] = self._prepare_image(haystack)[up:down, left:right]
                #self.image_logging = 10

                # uncomment this block in order to view the filling of the results
                # (marked with 1.0 when filled) and the different ndarray shapes
                #result[j][i] = 1.0
                #print result
                #print hregion.shape, hgray.shape, ngray.shape, result.shape, "\n"

                hkp, hdc, nkp, ndc = self._detect_features(hregion, ngray,
                                                           self.eq.current["fdetect"],
                                                           self.eq.current["fextract"])

                if len(nkp) < 4 or len(hkp) < 4:
                    result[j][i] = 0.0
                    continue

                mhkp, mnkp = self._match_features(hkp, hdc, nkp, ndc,
                                                  self.eq.current["fmatch"])

                if self.hotmap[1] < similarity or len(mnkp) < 4:
                    result[j][i] = self.hotmap[1]
                    continue

                self._project_needle_center(needle, mnkp, mhkp)

                result[j][i] = self.hotmap[1]
                if self.hotmap[1] < similarity:
                    continue
                else:
                    locations[(j, i)] = (left + self.hotmap[2][0],
                                         up + self.hotmap[2][1])
                    #print "(x,y):", locations[(j, i)]

                # uncomment this block in order to have a 30 sec window
                # to view the feature matching image logging (log.png)
                #cv2.imwrite("log.png", self.hotmap[0])
                #import time
                #time.sleep(30)

        # restore image logging
        self.image_logging = logging
        if self.image_logging <= 40:
            hotmap = cv.CreateMat(len(result), len(result[0]), cv.CV_8UC1)
            cv.ConvertScale(cv.fromarray(result), hotmap, scale = 255.0)
            self.hotmap[0] = numpy.asarray(hotmap)
            cv2.imwrite("log.png", self.hotmap[0])

        return result, locations

    def _detect_features(self, hgray, ngray, detect, extract):
        """
        Detect all keypoints and calculate their respective decriptors.

        Perform zooming in the picture if the number of detected features
        is too low to project later on.
        """
        hkeypoints, nkeypoints = [], []
        hfactor, nfactor = 1, 1
        i, maxzoom = 0, 5

        # minimum 4 features are required for calculating the homography matrix
        while len(hkeypoints) < 4 or len(nkeypoints) < 4 and i < maxzoom:
            i += 1

            if detect == "oldSURF":
                # build the old surf feature detector
                hessian_threshold = self.eq.parameters["fdetect"]["oldSURFdetect"].value
                detector = cv2.SURF(hessian_threshold)

                (hkeypoints, hdescriptors) = detector.detect(hgray, None, useProvidedKeypoints = False)
                (nkeypoints, ndescriptors) = detector.detect(ngray, None, useProvidedKeypoints = False)

            # include only methods tested for compatibility
            elif (detect in self.eq.algorithms["feature_detectors"]
                  and extract in self.eq.algorithms["feature_extractors"]):
                detector = cv2.FeatureDetector_create(detect)
                detector = self.eq.sync_backend_to_params(detector, "fdetect")
                extractor = cv2.DescriptorExtractor_create(extract)
                extractor = self.eq.sync_backend_to_params(extractor, "fextract")

                # keypoints
                hkeypoints = detector.detect(hgray)
                nkeypoints = detector.detect(ngray)

                # feature vectors (descriptors)
                (hkeypoints, hdescriptors) = extractor.compute(hgray, hkeypoints)
                (nkeypoints, ndescriptors) = extractor.compute(ngray, nkeypoints)

            else:
                raise ImageFinderMethodError

            # if less than minimum features, zoom in small images to detect more
            #print len(nkeypoints), len(hkeypoints)
            if len(nkeypoints) < 4:
                nmat = cv.fromarray(ngray)
                nmat_zoomed = cv.CreateMat(nmat.rows * 2, nmat.cols * 2, cv.CV_8UC1)
                nfactor *= 2
                logging.debug("Minimum 4 features are required while only %s from needle "\
                              "were detected - zooming x%i needle to increase them!",
                              len(nkeypoints), nfactor)
                #print nmat.rows, nmat.cols
                cv.Resize(nmat, nmat_zoomed)
                ngray = numpy.asarray(nmat_zoomed)
            if len(hkeypoints) < 4:
                hmat = cv.fromarray(hgray)
                hmat_zoomed = cv.CreateMat(hmat.rows * 2, hmat.cols * 2, cv.CV_8UC1)
                hfactor *= 2
                logging.debug("Minimum 4 features are required while only %s from haystack "\
                                "were detected - zooming x%i haystack to increase them!",
                                len(hkeypoints), hfactor)
                #print hmat.rows, hmat.cols
                cv.Resize(hmat, hmat_zoomed)
                hgray = numpy.asarray(hmat_zoomed)

        # reduce keypoint coordinates to the original image size
        for hkeypoint in hkeypoints:
            hkeypoint.pt = (hkeypoint.pt[0] / hfactor, hkeypoint.pt[1] / hfactor)
        for nkeypoint in nkeypoints:
            nkeypoint.pt = (nkeypoint.pt[0] / nfactor, nkeypoint.pt[1] / nfactor)

        # plot the detected features for image logging
        if self.image_logging <= 10:
            for hkp in hkeypoints:
                color = (0, 0, 255)
                x, y = hkp.pt
                cv2.circle(self.hotmap[0], (int(x),int(y)), 2, color, -1)

        return (hkeypoints, hdescriptors, nkeypoints, ndescriptors)

    def _match_features(self, hkeypoints, hdescriptors,
                        nkeypoints, ndescriptors, match):
        """
        Match two sets of keypoints based on their descriptors.
        """
        def ratio_test(matches):
            """
            The ratio test checks the first and second best match. If their
            ratio is close to 1.0, there are both good candidates for the
            match and the probabilty of error when choosing one is greater.
            Therefore these matches are ignored and thus only matches of
            greater probabilty are returned.
            """
            matches2 = []
            for m in matches:

                if len(m) > 1:
                    # smooth to make 0/0 case also defined as 1.0
                    smooth_dist1 = m[0].distance + 0.0000001
                    smooth_dist2 = m[1].distance + 0.0000001

                    #print smooth_dist1 / smooth_dist2, self.ratio
                    if (smooth_dist1 / smooth_dist2 < self.eq.parameters["fmatch"]["ratioThreshold"].value):
                        matches2.append(m[0])
                else:
                    matches2.append(m[0])

            #print "rt: %i\%i" % (len(matches2), len(matches))
            return matches2

        def symmetry_test(nmatches, hmatches):
            """
            Refines the matches with a symmetry test which extracts
            only the matches in agreement with both the haystack and needle
            sets of keypoints. The two keypoints must be best feature
            matching of each other to ensure the error by accepting the
            match is not too large.
            """
            matches2 = []
            for nm in nmatches:
                for hm in hmatches:

                    if nm.queryIdx == hm.trainIdx and nm.trainIdx == hm.queryIdx:
                        m = cv2.DMatch(nm.queryIdx, nm.trainIdx, nm.distance)
                        matches2.append(m)
                        break

            #print "st: %i\%i" % (len(matches2), len(matches))
            return matches2

        if match == "in-house":
            matcher = InHouseCV()

        # include only methods tested for compatibility
        elif match in self.eq.algorithms["feature_matchers"]:
            # build matcher and match feature vectors
            matcher = cv2.DescriptorMatcher_create(match)
            matcher = self.eq.sync_backend_to_params(matcher, "fmatch")
        else:
            raise ImageFinderMethodError

        # NOTE: comment the next block and uncomment this block currently
        # only for testing purposes (all comment chars are intentional!)
        #matches = matcher.regionMatch(ndescriptors, hdescriptors,
        #                              nkeypoints, hkeypoints)
        ##matches = [m[0] for m in matcher.knnMatch(ndescriptors, hdescriptors, 1)]

        # find and filter matches through tests
        if self.eq.parameters["fmatch"]["ratioTest"].value:
            matches = matcher.knnMatch(ndescriptors, hdescriptors, 2)
            matches = ratio_test(matches)
        else:
            matches = matcher.knnMatch(ndescriptors, hdescriptors, 1)
            matches = [m[0] for m in matches]
        if self.eq.parameters["fmatch"]["symmetryTest"].value:
            if self.eq.parameters["fmatch"]["ratioTest"].value:
                hmatches = matcher.knnMatch(hdescriptors, ndescriptors, 2)
                hmatches = ratio_test(hmatches)
            else:
                hmatches = matcher.knnMatch(hdescriptors, ndescriptors, 1)
                hmatches = [hm[0] for hm in hmatches]
            matches = symmetry_test(matches, hmatches)

        # prepare final matches
        match_hkeypoints = []
        match_nkeypoints = []
        matches = sorted(matches, key = lambda x: x.distance)
        for match in matches:
            #print match.distance
            match_hkeypoints.append(hkeypoints[match.trainIdx])
            match_nkeypoints.append(nkeypoints[match.queryIdx])

        # plot the matched features for image logging
        if self.image_logging <= 20:
            for mhkp in match_hkeypoints:
                # these matches are half the way to being good
                color = (0, 255, 255)
                x, y = mhkp.pt
                cv2.circle(self.hotmap[0], (int(x),int(y)), 2, color, -1)

        # update the current achieved similarity
        self.hotmap[1] = float(len(match_nkeypoints)) / float(len(nkeypoints))
        #print "%s\\%s" % (len(mnkp), len(nkp)), "-> %f" % self.hotmap[1]

        return (match_hkeypoints, match_nkeypoints)

    def _project_needle_center(self, needle, mnkp, mhkp):
        """
        Calculate the needle projection using random sample consensus
        and the matched keypoints between the needle and the haystack.

        @param needle: the original needle image
        @param mnkp: matched needle keypoints
        @param mhkp: matched haystack keypoints
        """
        # check matches consistency
        assert(len(mnkp) == len(mhkp))

        # homography and fundamental matrix as options - homography is considered only
        # for rotation but currently gives better results than the fundamental matrix
        H, mask = cv2.findHomography(numpy.array([kp.pt for kp in mnkp]),
                                     numpy.array([kp.pt for kp in mhkp]), cv2.RANSAC,
                                     self.eq.parameters["find"]["ransacReprojThreshold"].value)
        #H, mask = cv2.findFundamentalMat(numpy.array([kp.pt for kp in mnkp]),
        #                                 numpy.array([kp.pt for kp in mhkp]),
        #                                 method = cv2.RANSAC, param1 = 10.0,
        #                                 param2 = 0.9)

        # measure total used features for the projected focus point
        total_matches = 0
        for kp in mhkp:
            # true matches are also inliers for the homography
            if mask[mhkp.index(kp)][0] == 1:
                total_matches += 1
                # plot the correctly projected features
                if self.image_logging <= 30:
                    color = (0, 255, 0)
                    x, y = kp.pt
                    cv2.circle(self.hotmap[0], (int(x),int(y)), 2, color, -1)

        # calculate and project center coordinates
        (ocx, ocy) = (needle.get_width() / 2, needle.get_height() / 2)
        orig_center_wrapped = numpy.array([[[ocx, ocy]]], dtype = numpy.float32)
        #print orig_center_wrapped.shape, H.shape
        match_center_wrapped = cv2.perspectiveTransform(orig_center_wrapped, H)
        (mcx, mcy) = (match_center_wrapped[0][0][0], match_center_wrapped[0][0][1])

        # plot the focus point used for clicking and other operations
        if self.image_logging <= 40:
            cv2.circle(self.hotmap[0], (int(mcx),int(mcy)), 4, (255,0,0), -1)

        self.hotmap[1] = float(total_matches) / float(len(mnkp))
        #print "%s\\%s" % (total_matches, len(mnkp)), "-> %f" % self.hotmap[1]
        self.hotmap[2] = (int(mcx), int(mcy))

        return H

    def _prepare_image(self, image, gray = False):
        """
        Convert the Image() object into compatible numpy array
        and into grayscale if the gray parameter is True.
        """
        searchable_image = numpy.array(image.get_pil_image())
        # convert RGB to BGR
        searchable_image = searchable_image[:, :, ::-1].copy()
 
        if gray:
            searchable_image = cv2.cvtColor(searchable_image, cv2.COLOR_BGR2GRAY)

        return searchable_image

    def _match_template(self, haystack, needle, nocolor, match):
        """
        Match a color or grayscale needle image using the OpenCV
        template matching methods.
        """
        # Sanity check: Needle size must be smaller than haystack
        if haystack.get_width() < needle.get_width() or haystack.get_height() < needle.get_height():
            logging.warning("The size of the searched image is smaller than its region")
            return None

        methods = {"sqdiff" : cv2.TM_SQDIFF, "sqdiff_normed" : cv2.TM_SQDIFF_NORMED,
                   "ccorr" : cv2.TM_CCORR, "ccorr_normed" : cv2.TM_CCORR_NORMED,
                   "ccoeff" : cv2.TM_CCOEFF, "ccoeff_normed" : cv2.TM_CCOEFF_NORMED}
        if match not in methods.keys():
            raise ImageFinderMethodError

        if nocolor:
            gray_haystack = self._prepare_image(haystack, gray = True)
            gray_needle = self._prepare_image(needle, gray = True)
            match = cv2.matchTemplate(gray_haystack, gray_needle, methods[match])
        else:
            opencv_haystack = self._prepare_image(haystack, gray = False)
            opencv_needle = self._prepare_image(needle, gray = False)
            match = cv2.matchTemplate(opencv_haystack, opencv_needle, methods[match])

        return match


class InHouseCV:
    """
    ImageFinder backend with in-house CV algorithms.
    """

    def __init__(self):
        """Initiate thee CV backend attributes."""
        self.detector = cv2.FeatureDetector_create("ORB")
        self.extractor = cv2.DescriptorExtractor_create("ORB")

    def detect_features(self, haystack, needle):
        """
        In-house feature detect algorithm - currently not fully implemented!

        The current MSER might not be used in the actual implementation.
        """
        opencv_haystack = self._prepare_image(haystack)
        opencv_needle = self._prepare_image(needle)
        hgray = self._prepare_image(haystack, gray = True)
        ngray = self._prepare_image(needle, gray = True)

        # TODO: this MSER blob feature detector is also available in
        # version 2.2.3 - implement if necessary
        detector = cv2.MSER()
        hregions = detector.detect(hgray, None)
        nregions = detector.detect(ngray, None)
        hhulls = [cv2.convexHull(p.reshape(-1, 1, 2)) for p in hregions]
        nhulls = [cv2.convexHull(p.reshape(-1, 1, 2)) for p in nregions]
        # show on final result
        cv2.polylines(opencv_haystack, hhulls, 1, (0, 255, 0))
        cv2.polylines(opencv_needle, nhulls, 1, (0, 255, 0))

        return None

    def regionMatch(self, desc1, desc2, kp1, kp2,
                    refinements = 100, recalc_interval = 10,
                    variants_k = 100, variants_ratio = 0.5):
        """
        Use location information to better decide on matched features.

        The knn distance is now only a heuristic for the search of best
        matched set as is information on relative location with regard
        to the other matches.

        @param refinements: number of points to relocate
        @param recalc_interval: recalculation on a number of refinements
        @param variants_k: kNN parameter for to limit the alternative variants
            of a badly positioned feature
        @param variants_ratio: internal ratio test for knnMatch autostop (see below)

        TODO: handle a subset of matches (ignoring some matches if not all features are detected)
        TODO: disable kernel mapping (multiple needle feature mapped to a single haystack feature)
        """
        def ncoord(match):
            return kp1[match.queryIdx].pt

        def hcoord(match):
            return kp2[match.trainIdx].pt

        def rcoord(origin, target):
            # True is right/up or coinciding, False is left/down
            coord = [0, 0]
            if target[0] < origin[0]:
                coord[0] = -1
            elif target[0] > origin[0]:
                coord[0] = 1
            if target[1] < origin[1]:
                coord[1] = -1
            elif target[1] > origin[1]:
                coord[1] = 1
            #print origin, ":", target, "=", coord
            return coord

        def compare_pos(match1, match2):
            hc = rcoord(hcoord(match1), hcoord(match2))
            nc = rcoord(ncoord(match1), ncoord(match2))

            valid_positioning = True
            if hc[0] != nc[0] and hc[0] != 0 and nc[0] != 0:
                valid_positioning = False
            if hc[1] != nc[1] and hc[1] != 0 and nc[1] != 0:
                valid_positioning = False

            #print "p1:p2 = %s in haystack and %s in needle" % (hc, nc)
            #print "is their relative positioning valid? %s" % valid_positioning

            return valid_positioning

        def match_cost(matches, new_match):
            if len(matches) == 0:
                return 0.0

            nominator = sum(float(not compare_pos(match, new_match)) for match in matches)
            denominator = float(len(matches))
            ratio = nominator / denominator
            #print "model <-> match = %i disagreeing / %i total matches" % (nominator, denominator)

            # avoid 0 mapping, i.e. giving 0 positional
            # conflict to 0 distance matches or 0 distance
            # to matches with 0 positional conflict
            if ratio == 0.0 and new_match.distance != 0.0:
                ratio = 0.001
            elif new_match.distance == 0.0 and ratio != 0.0:
                new_match.distance = 0.001

            cost = ratio * new_match.distance
            #print "would be + %f cost" % cost
            #print "match reduction: ", cost / max(sum(m.distance for m in matches), 1)

            return cost

        results = self.knnMatch(desc1, desc2, variants_k,
                                1, variants_ratio)
        matches = [variants[0] for variants in results]
        ratings = [None for _ in matches]
        #print "%i matches in needle to start with" % len(matches)

        # minimum one refinement is needed
        refinements = max(1, refinements)
        for i in range(refinements):

            # recalculate all ratings on some interval to save performance
            if i % recalc_interval == 0:
                for j in range(len(matches)):
                    # ratings forced to 0.0 cannot be improved
                    # because there are not better variants to use
                    if ratings[j] != 0.0:
                        ratings[j] = match_cost(matches, matches[j])
                quality = sum(ratings)
                #print "recalculated quality:", quality
                # nothing to improve if quality is perfect
                if quality == 0.0:
                    break

            outlier_index = ratings.index(max(ratings))
            outlier = matches[outlier_index]
            variants = results[outlier_index]
            #print "outlier m%i with rating %i" % (outlier_index, max(ratings))
            #print "%i match variants for needle match %i" % (len(variants), outlier_index)

            # add the match variant with a minimal cost
            variant_costs = []
            curr_cost_index = variants.index(outlier)
            for j, variant in enumerate(variants):

                # speed up using some heuristics
                if j > 0:
                    # cheap assertion paid for with the speedup
                    assert(variants[j].queryIdx == variants[j-1].queryIdx)
                    if variants[j].trainIdx == variants[j-1].trainIdx:
                        continue

                #print "variant %i is m%i/%i in n/h" % (j, variant.queryIdx, variant.trainIdx)
                #print "variant %i coord in n/h" % j, ncoord(variant), "/", hcoord(variant)
                #print "variant distance:", variant.distance

                matches[outlier_index] = variant
                variant_costs.append((j, match_cost(matches, variant)))

            min_cost_index, min_cost = min(variant_costs, key = lambda x: x[1])
            min_cost_variant = variants[min_cost_index]
            #if variant_costs.index(min(variant_costs)) != 0:
            #print variant_costs, ">", min_cost, "i.e. variant", min_cost_index
            matches[outlier_index] = min_cost_variant
            ratings[outlier_index] = min_cost

            # when the best variant is the selected for improvement
            if min_cost_index == curr_cost_index:
                ratings[outlier_index] = 0.0

            # 0.0 is best quality
            #print "overall quality:", sum(ratings)
            #print "reduction: ", sum(ratings) / max(sum(m.distance for m in matches), 1)

        return matches

    def knnMatch(self, desc1, desc2, k = 1, desc4kp = 1, autostop = 0.0):
        """
        In-house feature matching algorithm taking needle and haystack
        keypoints and their descriptors and returning a list of DMatch
        tuples (first and second best match).

        Performs k-Nearest Neighbor matching.

        @param desc1, desc1: descriptors of the matched images
        @param k: categorization up to k-th nearest neighbor
        @param desc4kp: legacy parameter for the old SURF() feature detector
        where desc4kp = len(desc2) / len(kp2) or analogically len(desc1) / len(kp1)
        i.e. needle row 5 is a descriptor vector for needle keypoint 5
        @param autostop: stop automatically if the ratio (dist to k)/(dist to k+1)
        is close to 0, i.e. the k+1-th neighbor is too far.
        """
        if desc4kp > 1:
            desc1 = numpy.array(desc1, dtype = numpy.float32).reshape((-1, desc4kp))
            desc2 = numpy.array(desc2, dtype = numpy.float32).reshape((-1, desc4kp))
            #print desc1.shape, desc2.shape
        else:
            desc1 = numpy.array(desc1, dtype = numpy.float32)
            desc2 = numpy.array(desc2, dtype = numpy.float32)
        desc_size = desc2.shape[1]

        # kNN training - learn mapping from rows2 to kp2 index
        samples = desc2
        responses = numpy.arange(int(len(desc2)/desc4kp), dtype = numpy.float32)
        #print len(samples), len(responses)
        knn = cv2.KNearest()
        knn.train(samples, responses, maxK = k)

        matches = []
        # retrieve index and value through enumeration
        for i, descriptor in enumerate(desc1):
            descriptor = numpy.array(descriptor, dtype = numpy.float32).reshape((1, desc_size))
            #print i, descriptor.shape, samples[0].shape
            kmatches = []
            ratio = 1.0

            for ki in range(k):
                _, res, _, dists = knn.find_nearest(descriptor, ki+1)
                #print ki, res, dists
                if len(dists[0]) > 1 and autostop > 0.0:

                    # TODO: perhaps ratio from first to last ki?
                    # smooth to make 0/0 case also defined as 1.0
                    dist1 = dists[0][-2] + 0.0000001
                    dist2 = dists[0][-1] + 0.0000001
                    ratio = dist1 / dist2
                    #print ratio, autostop
                    if ratio < autostop:
                        break

                kmatches.append(cv2.DMatch(i, int(res[0][0]), dists[0][-1]))

            matches.append(tuple(kmatches))
        return matches
