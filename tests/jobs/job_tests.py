import json
import unittest
import subprocess
import random
import traceback

from sqlalchemy.exc import NoSuchTableError

from plenario import create_app
from plenario.api import prefix
from plenario.api.jobs import *
from plenario.database import app_engine, session
from plenario.models import MetaTable, ShapeMetadata
from plenario.update import create_worker
from plenario.utils.model_helpers import fetch_table, table_exists
from plenario.views import approve_dataset, update_dataset, delete_dataset
from plenario.views import approve_shape, update_shape, delete_shape
from tests.points.api_tests import get_loop_rect
from tests.test_fixtures.base_test import BasePlenarioTest


class TestJobs(unittest.TestCase):

    currentTicket = ""

    @staticmethod
    def flush_fixtures():
        sql = "delete from meta_master where dataset_name = 'restaurant_applications'"
        app_engine.execute(sql)
        sql = "delete from meta_shape where dataset_name = 'boundaries_neighborhoods'"
        app_engine.execute(sql)

    @classmethod
    def setUpClass(cls):

        super(TestJobs, cls).setUpClass()

        # FOR THIS TEST TO WORK
        # You need to specify the AWS Keys and the Jobs Queue
        # in the environment variables. On travis, this will be
        # done automatically.

        # setup flask app instance
        cls.app = create_app().test_client()
        cls.other_app = create_app()
        # setup flask app instance for worker
        cls.worker = create_worker().test_client()
        # start worker
        subprocess.Popen(["python", "worker.py"])
        # give worker time to start up
        time.sleep(3)

        # Clearing out the DB.
        try:
            TestJobs.flush_fixtures()
        except:
            pass

        # Seeding the database for ETL Tests.
        restaurants = dict([('col_name_decisiontargetdate', u''), ('col_name_classificationlabel', u''), ('col_name_publicconsultationenddate', u''), ('col_name_locationtext', u''), ('view_url', u'https://opendata.bristol.gov.uk/api/views/5niz-5v5u/rows'), ('dataset_description', u'Planning applications details for applications from 2010 to 2014. Locations have been geocoded based on postcode where available.'), ('col_name_decisionnoticedate', u''), ('col_name_casetext', u''), ('update_frequency', u'yearly'), ('col_name_status', u''), ('col_name_location', u'location'), ('col_name_publicconsultationstartdate', u''), ('contributor_email', u'look@me.com'), ('col_name_decision', u''), ('col_name_decisiontype', u''), ('col_name_organisationuri', u''), ('col_name_appealref', u''), ('col_name_coordinatereferencesystem', u''), ('col_name_appealdecision', u''), ('col_name_geoarealabel', u''), ('col_name_organisationlabel', u''), ('contributor_organization', u''), ('col_name_casereference', u''), ('col_name_latitude', u''), ('col_name_servicetypelabel', u''), ('is_shapefile', u'false'), ('col_name_groundarea', u''), ('col_name_postcode', u''), ('col_name_agent', u''), ('col_name_classificationuri', u''), ('col_name_geoy', u''), ('col_name_geox', u''), ('col_name_uprn', u''), ('col_name_geopointlicencingurl', u''), ('col_name_appealdecisiondate', u''), ('col_name_decisiondate', u''), ('col_name_extractdate', u'observed_date'), ('col_name_servicetypeuri', u''), ('col_name_casedate', u''), ('dataset_attribution', u'Bristol City Council'), ('col_name_caseurl', u''), ('contributor_name', u'mrmeseeks'), ('col_name_publisheruri', u''), ('col_name_geoareauri', u''), ('col_name_postcode_sector', u''), ('file_url', u'https://opendata.bristol.gov.uk/api/views/5niz-5v5u/rows.csv?accessType=DOWNLOAD'), ('col_name_postcode_district', u''), ('col_name_publisherlabel', u''), ('col_name_responsesfor', u''), ('col_name_responsesagainst', u''), ('col_name_longitude', u''), ('dataset_name', u'restaurant_applications')])
        boundaries = dict([('dataset_attribution', u'City of Chicago'), ('contributor_name', u'mrmeseeks'), ('view_url', u''), ('file_url', u'https://data.cityofchicago.org/api/geospatial/bbvz-uum9?method=export&format=Shapefile'), ('contributor_organization', u''), ('dataset_description', u'Neighborhood boundaries in Chicago, as developed by the Office of Tourism. These boundaries are approximate and names are not official. The data can be viewed on the Chicago Data Portal with a web browser. However, to view or use the files outside of a web browser, you will need to use compression software and special GIS software, such as ESRI ArcGIS (shapefile) or Google Earth (KML or KMZ), is required.'), ('update_frequency', u'yearly'), ('contributor_email', u'look@me.com'), ('is_shapefile', u'true'), ('dataset_name', u'boundaries_neighborhoods')])
        cls.app.post('/add?is_shapefile=false', data=restaurants)
        cls.app.post('/add?is_shapefile=true', data=boundaries)

    # ========================= FUNCTIONALITY TESTS ========================== #

    # =======================
    # TEST: General Job Methods: submit_job, get_status, get_request, get_result
    # =======================

    def test_job_submission_by_methods(self):
        ticket = submit_job({"endpoint": "ping", "query": {"test": "abcdefg"}})
        self.assertIsNotNone(ticket)
        status = get_status(ticket)
        self.assertTrue(status["status"] in ["queued", "processing", "success"])
        req = get_request(ticket)
        self.assertEqual(req["endpoint"], "ping")
        self.assertEqual(req["query"]["test"], "abcdefg")

        # Wait for job to complete.
        for i in range(30):
            if get_status(ticket)["status"] == "success":
                break
            time.sleep(1)

        self.assertEqual(get_status(ticket)["status"], "success")
        result = get_result(ticket)
        self.assertIsNotNone(result["hello"])

    # =======================
    # TEST: Job Mutators: set_status, set_request, set_result
    # =======================

    def test_job_mutators(self):
        ticket = "atestticket"

        set_status(ticket, {"status": "funny"})
        self.assertEqual(get_status(ticket), {"status": "funny"})

        set_request(ticket, {"endpoint": "narnia"})
        self.assertEqual(get_request(ticket), {"endpoint": "narnia"})

        set_result(ticket, "the_final_countdown")
        self.assertEqual(get_result(ticket), "the_final_countdown")

    # ============================================================
    # TEST: Admin DB Actions: add, update, delete (meta/shapemeta)
    # ============================================================
    # These tests rely on the 2010_2014_restaurant_applications dataset to
    # be present in the MetaTable and the boundaries_neighborhoods dataset
    # to be present in the ShapeMetadata
    #
    # Links:
    #   https://opendata.bristol.gov.uk/api/views/5niz-5v5u/rows.csv
    #   https://data.cityofchicago.org/api/geospatial/bbvz-uum9?method=export&format=Shapefile

    def admin_test_01_approve_dataset(self):

        # Grab the source url hash.
        dname = 'restaurant_applications'

        # Drop the table if it already exists.
        if table_exists(MetaTable, dname):
            fetch_table(MetaTable, dname).drop()

        q = session.query(MetaTable.source_url_hash)
        source_url_hash = q.filter(MetaTable.dataset_name == dname).scalar()

        # Queue the ingestion job.
        ticket = approve_dataset(source_url_hash)

        wait_on(ticket, 15)
        status = get_status(ticket)['status']

        # First check if it finished correctly.
        self.assertIn(status, ['error', 'success'])
        # Then check if the job was successful.
        self.assertEqual(status, 'success')
        # Now check if the ingestion process ran correctly.
        table = MetaTable.get_by_dataset_name(dname).point_table
        count = len(session.query(table).all())
        self.assertEqual(count, 356)

    def admin_test_02_update_dataset(self):

        # Grab source url hash.
        dname = 'restaurant_applications'
        q = session.query(MetaTable.source_url_hash)
        source_url_hash = q.filter(MetaTable.dataset_name == dname).scalar()

        table = MetaTable.get_by_dataset_name(dname).point_table

        # Queue the update job.
        with self.other_app.test_request_context():
            ticket = update_dataset(source_url_hash).data
            ticket = json.loads(ticket)['ticket']
        wait_on(ticket, 15)
        status = get_status(ticket)['status']
        self.assertIn(status, {'error', 'success'})
        self.assertEqual(status, 'success')
        count = len(session.query(table).all())
        self.assertEqual(count, 356)

    def admin_test_03_delete_dataset(self):

        # Get source url hash.
        dname = 'restaurant_applications'
        q = session.query(MetaTable.source_url_hash)
        source_url_hash = q.filter(MetaTable.dataset_name == dname).scalar()

        table = MetaTable.get_by_dataset_name(dname).point_table
        self.assertTrue(table is not None)

        # Queue the deletion job.
        with self.other_app.test_request_context():
            ticket = delete_dataset(source_url_hash)
            ticket = json.loads(ticket.data)['ticket']
        wait_on(ticket, 10)
        status = get_status(ticket)['status']
        self.assertIn(status, {'error', 'success'})
        self.assertEqual(status, 'success')

        table = MetaTable.get_by_dataset_name(dname)
        self.assertTrue(table is None)

    def admin_test_04_approve_shapeset(self):
        print "TEST 04 ============================="

        shape_name = 'boundaries_neighborhoods'

        # Drop the table if it already exists.
        try:
            table = ShapeMetadata.get_by_dataset_name(shape_name).shape_table
            table.drop()
        except NoSuchTableError:
            pass

        # Queue the ingestion job.
        with self.other_app.test_request_context():
            ticket = approve_shape(shape_name)

        print "shape_test.ticket: {}".format(ticket)

        wait_on(ticket, 20)
        status = get_status(ticket)['status']

        # First check if it finished correctly.
        self.assertIn(status, ['error', 'success'])
        # Then check if the job was successful.
        self.assertEqual(status, 'success')

        # Now check if the ingestion process ran correctly.
        table = ShapeMetadata.get_by_dataset_name(shape_name).shape_table
        count = len(session.query(table).all())
        self.assertEqual(count, 98)

    def admin_test_05_update_shapeset(self):
        print "TEST 05 ============================="

        # Grab source url hash.
        shape_name = 'boundaries_neighborhoods'

        table = ShapeMetadata.get_by_dataset_name(shape_name).shape_table

        # Queue the update job.
        with self.other_app.test_request_context():
            ticket = update_shape(shape_name).data
            ticket = json.loads(ticket)['ticket']
        wait_on(ticket, 15)
        status = get_status(ticket)['status']
        self.assertIn(status, {'error', 'success'})
        self.assertEqual(status, 'success')
        count = len(session.query(table).all())
        self.assertEqual(count, 98)

    # TODO: Why does including this test break the other shape tests?
    # def admin_test_06_delete_shapeset(self):
    #     print "TEST 06 ============================="
    #
    #     Get source url hash.
    #     shape_name = 'boundaries_neighborhoods'
    #
    #     Queue the deletion job.
    #     with self.other_app.test_request_context():
    #         ticket = delete_shape(shape_name)
    #         ticket = json.loads(ticket.data)['ticket']
    #         print 'shape_delete.ticket: {}'.format(ticket)
    #     wait_on(ticket, 20)
    #     status = get_status(ticket)['status']
    #     self.assertIn(status, {'error', 'success'})
    #     self.assertEqual(status, 'success')
    #
    #     table = ShapeMetadata.get_by_dataset_name(shape_name)
    #     self.assertTrue(table is None)

    # =======================
    # ACCEPTANCE TEST: Job submission
    # =======================

    def test_job_submission_by_api(self):

        # submit job
        # /datasets with a cachebuster at the end
        response = self.app.get(prefix + '/datasets?job=true&obs_date__ge=2010-07-08&'+str(random.randrange(0,1000000)))
        response = json.loads(response.get_data())
        ticket = response["ticket"]
        self.assertIsNotNone(ticket)
        self.assertIsNotNone(response["url"])
        self.assertEqual(response["request"]["endpoint"], "meta")
        self.assertEqual(response["request"]["query"]["obs_date__ge"], "2010-07-08")

        # retrieve job
        url = response["url"]
        response = self.app.get(url)
        response = json.loads(response.get_data())
        self.assertTrue(response["status"]["status"] in ["queued", "processing", "success"])
        self.assertIsNotNone(response["status"]["meta"]["queueTime"])
        self.assertEqual(response["ticket"], ticket)

        # Wait for job to complete.
        for i in range(30):
            if get_status(ticket)["status"] == "success":
                break
            time.sleep(1)

        response = self.app.get(url)
        response = json.loads(response.get_data())
        self.assertIsNotNone(response["status"]["meta"]["startTime"])
        self.assertIsNotNone(response["status"]["meta"]["endTime"])
        self.assertIsNotNone(response["status"]["meta"]["worker"])
        self.assertGreater(json.dumps(response["result"]), len("{\"\"}"))

    # =======================
    # ACCEPTANCE TEST: Get non-existent job
    # =======================

    def test_bad_job_retrieval(self):

        # dummy job with a cachebuster at the end
        ticket = "for_sure_this_isnt_a_job_because_jobs_are_in_hex"
        response = self.app.get(prefix + "/jobs/" + ticket + "?&" + str(random.randrange(0, 1000000)))
        response = json.loads(response.get_data())
        self.assertEqual(response["ticket"], ticket)
        self.assertIsNotNone(response["error"])

    # ============================ ENDPOINT TESTS ============================ #

    # =======================
    # ACCEPTANCE TEST: timeseries
    # =======================

    def test_timeseries_job(self):
        response = self.app.get(prefix + '/timeseries/?obs_date__ge=2013-09-22&obs_date__le=2013-10-1&agg=day&job=true&' + str(random.randrange(0, 1000000)))
        response = json.loads(response.get_data())
        ticket = response["ticket"]
        self.assertIsNotNone(ticket)
        self.assertIsNotNone(response["url"])
        self.assertEqual(response["request"]["endpoint"], "timeseries")
        self.assertEqual(response["request"]["query"]["obs_date__ge"], "2013-09-22")
        self.assertEqual(response["request"]["query"]["obs_date__le"], "2013-10-01")
        self.assertEqual(response["request"]["query"]["agg"], "day")
        self.assertEqual(response["request"]["query"]["job"], True)

        # Wait for job to complete.
        for i in range(30):
            if get_status(ticket)["status"] == "success":
                break
            time.sleep(1)

        # retrieve job
        url = response["url"]
        response = self.app.get(url)
        response = json.loads(response.get_data())
        self.assertFalse("error" in response.keys())
        self.assertEqual(response["status"]["status"], "success")
        self.assertEqual(len(response["result"]), 1)
        self.assertEqual(response["result"][0]["source_url"], "https://data.cityofchicago.org/api/views/rfdj-hdmf/rows.csv?accessType=DOWNLOAD")
        self.assertEqual(response["result"][0]["count"], 5)
        self.assertEqual(response["result"][0]["dataset_name"], "flu_shot_clinics")

    # =======================
    # ACCEPTANCE TEST: detail-aggregate
    # =======================

    def test_detail_aggregate_job(self):
        response = self.app.get(
            prefix + '/detail-aggregate/?dataset_name=flu_shot_clinics&obs_date__ge=2013-09-22&obs_date__le=2013-10-1&agg=week&job=true&' + str(
                random.randrange(0, 1000000)))
        response = json.loads(response.get_data())
        ticket = response["ticket"]
        self.assertIsNotNone(ticket)
        self.assertIsNotNone(response["url"])
        self.assertEqual(response["request"]["endpoint"], "detail-aggregate")
        self.assertEqual(response["request"]["query"]["obs_date__ge"], "2013-09-22")
        self.assertEqual(response["request"]["query"]["obs_date__le"], "2013-10-01")
        self.assertEqual(response["request"]["query"]["agg"], "week")
        self.assertEqual(response["request"]["query"]["job"], True)

        # Wait for job to complete.
        for i in range(30):
            if get_status(ticket)["status"] == "success":
                break
            time.sleep(1)

        # retrieve job
        url = response["url"]
        response = self.app.get(url)
        response = json.loads(response.get_data())
        self.assertFalse("error" in response.keys())
        self.assertEqual(response["status"]["status"], "success")
        self.assertEqual(response["request"]["query"]["dataset"], "flu_shot_clinics")
        self.assertEqual(len(response["result"]), 3)
        self.assertEqual(response["result"][0]["count"], 1)
        self.assertEqual(response["result"][0]["datetime"], "2013-09-16")

    # =======================
    # ACCEPTANCE TEST: detail
    # =======================

    def test_detail_job(self):
        response = self.app.get(
            prefix + '/detail/?dataset_name=flu_shot_clinics&obs_date__ge=2013-09-22&obs_date__le=2013-10-1&shape=chicago_neighborhoods&job=true&' + str(
                random.randrange(0, 1000000)))
        response = json.loads(response.get_data())
        ticket = response["ticket"]
        self.assertIsNotNone(ticket)
        self.assertIsNotNone(response["url"])
        self.assertEqual(response["request"]["endpoint"], "detail")
        self.assertEqual(response["request"]["query"]["obs_date__ge"], "2013-09-22")
        self.assertEqual(response["request"]["query"]["obs_date__le"], "2013-10-01")
        self.assertEqual(response["request"]["query"]["dataset"], "flu_shot_clinics")
        self.assertEqual(response["request"]["query"]["shapeset"], "chicago_neighborhoods")
        self.assertEqual(response["request"]["query"]["job"], True)

        # Wait for job to complete.
        for i in range(30):
            if get_status(ticket)["status"] == "success":
                break
            time.sleep(1)

        # retrieve job
        url = response["url"]
        response = self.app.get(url)
        response = json.loads(response.get_data())
        self.assertFalse("error" in response.keys())
        self.assertEqual(response["status"]["status"], "success")
        self.assertEqual(len(response["result"]), 5)

    # =======================
    # ACCEPTANCE TEST: meta
    # =======================

    def test_meta_job(self):
        response = self.app.get(
            prefix + '/datasets/?dataset_name=flu_shot_clinics&job=true&' + str(
                random.randrange(0, 1000000)))
        response = json.loads(response.get_data())
        ticket = response["ticket"]
        self.assertIsNotNone(ticket)
        self.assertIsNotNone(response["url"])
        self.assertEqual(response["request"]["endpoint"], "meta")
        self.assertEqual(response["request"]["query"]["dataset"], "flu_shot_clinics")
        self.assertEqual(response["request"]["query"]["job"], True)

        # Wait for job to complete.
        for i in range(30):
            if get_status(ticket)["status"] == "success":
                break
            time.sleep(1)

        # retrieve job
        url = response["url"]
        response = self.app.get(url)
        response = json.loads(response.get_data())
        self.assertFalse("error" in response.keys())
        self.assertEqual(response["status"]["status"], "success")
        self.assertEqual(len(response["result"]), 1)
        self.assertEqual(response["result"][0]["source_url"], "https://data.cityofchicago.org/api/views/rfdj-hdmf/rows.csv?accessType=DOWNLOAD")
        self.assertEqual(response["result"][0]["human_name"], "Flu Shot Clinic Locations")
        self.assertEqual(len(response["result"][0]["columns"]), 17)

    # =======================
    # ACCEPTANCE TEST: fields
    # =======================

    def test_fields_job(self):
        response = self.app.get(
            prefix + '/fields/flu_shot_clinics?job=true&' + str(
                random.randrange(0, 1000000)))
        response = json.loads(response.get_data())
        ticket = response["ticket"]
        self.assertIsNotNone(ticket)
        self.assertIsNotNone(response["url"])
        self.assertEqual(response["request"]["endpoint"], "fields")
        self.assertEqual(response["request"]["query"]["job"], True)

        # Wait for job to complete.
        for i in range(30):
            if get_status(ticket)["status"] == "success":
                break
            time.sleep(1)

        # retrieve job
        url = response["url"]
        response = self.app.get(url)
        response = json.loads(response.get_data())
        self.assertFalse("error" in response.keys())
        self.assertEqual(response["status"]["status"], "success")
        self.assertEqual(len(response["result"]), 1)
        self.assertEqual(len(response["result"][0]["columns"]), 17)
        self.assertEqual(response["result"][0]["columns"][0]["field_type"], "VARCHAR")
        self.assertEqual(response["result"][0]["columns"][0]["field_name"], "city")

    # =======================
    # ACCEPTANCE TEST: grid
    # =======================

    def test_grid_job(self):

        # Get location geom string (non-escaped) for verification
        import os
        pwd = os.path.dirname(os.path.realpath(__file__))
        rect_path = os.path.join(pwd, '../test_fixtures/loop_rectangle.json')
        with open(rect_path, 'r') as rect_json:
            query_rect = rect_json.read()

        response = self.app.get(
            prefix + '/grid/?obs_date__ge=2013-1-1&obs_date__le=2014-1-1&dataset_name=flu_shot_clinics&location_geom__within=' + get_loop_rect() + '&job=true&' + str(
                random.randrange(0, 1000000)))
        response = json.loads(response.get_data())
        ticket = response["ticket"]
        self.assertIsNotNone(ticket)
        self.assertIsNotNone(response["url"])
        self.assertEqual(response["request"]["endpoint"], "grid")
        self.assertEqual(response["request"]["query"]["dataset"], "flu_shot_clinics")
        self.assertEqual(response["request"]["query"]["obs_date__ge"], "2013-01-01")
        self.assertEqual(response["request"]["query"]["obs_date__le"], "2014-01-01")
        self.assertEqual(json.loads(response["request"]["query"]["geom"])["coordinates"], json.loads(query_rect)["geometry"]["coordinates"])
        self.assertEqual(response["request"]["query"]["job"], True)

        # Wait for job to complete.
        for i in range(30):
            if get_status(ticket)["status"] == "success":
                break
            time.sleep(1)

        # retrieve job
        url = response["url"]
        response = self.app.get(url)
        response = json.loads(response.get_data())
        self.assertFalse("error" in response.keys())
        self.assertEqual(response["status"]["status"], "success")
        self.assertEqual(len(response["result"]["features"]), 4)
        self.assertEqual(response["result"]["type"], "FeatureCollection")
        self.assertEqual(response["result"]["features"][0]["properties"]["count"], 1)

    @classmethod
    def tearDownClass(cls):
        print("Stopping worker.")
        subprocess.Popen(["pkill", "-f", "worker.py"])

        # Clear out the DB.
        try:
            TestJobs.flush_fixtures()
        except:
            pass

        # Release the locks on Postgres.
        session.close()


def wait_on(ticket, seconds):

    if ticket is None:
        return
    for i in range(seconds):
        status = get_status(ticket)['status']
        if status == 'success' or status == 'error':
            break
        time.sleep(1)