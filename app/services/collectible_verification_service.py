import requests
import json
from datetime import datetime
from ..models import CollectibleVerification, VerificationLog, SupportedGrader, Product
from ..extensions import db

class GraderAPIClient:
    """Base class for grader API integrations"""

    def __init__(self, grader_name, api_key=None):
        self.grader_name = grader_name
        self.api_key = api_key

    def lookup_certificate(self, cert_number):
        """Override in subclass for specific grader"""
        raise NotImplementedError


class PSAAPIClient(GraderAPIClient):
    """PSA (Professional Sports Authenticator) API client"""

    def __init__(self, api_key=None):
        super().__init__('PSA', api_key)
        self.base_url = "https://api.psacard.com"

    def lookup_certificate(self, cert_number):
        """Lookup PSA certificate number"""
        try:
            endpoint = f"{self.base_url}/v1/cert/{cert_number}"
            headers = {'Authorization': f'Bearer {self.api_key}'} if self.api_key else {}

            response = requests.get(endpoint, headers=headers, timeout=10)
            response.raise_for_status()

            return {
                'status': 'success',
                'data': response.json(),
                'url': f"https://www.psacard.com/cert/{cert_number}"
            }
        except requests.exceptions.RequestException as e:
            return {
                'status': 'failed',
                'error': str(e)
            }


class PCGSAPIClient(GraderAPIClient):
    """PCGS (Professional Coin Grading Service) API client"""

    def __init__(self, api_key=None):
        super().__init__('PCGS', api_key)
        self.base_url = "https://www.pcgs.com/services/certlookup"

    def lookup_certificate(self, cert_number):
        """Lookup PCGS certificate number"""
        try:
            params = {'cert': cert_number}
            response = requests.get(self.base_url, params=params, timeout=10)
            response.raise_for_status()

            return {
                'status': 'success',
                'data': response.json(),
                'url': f"https://www.pcgs.com/cert/{cert_number}"
            }
        except requests.exceptions.RequestException as e:
            return {
                'status': 'failed',
                'error': str(e)
            }


class NGCAPIClient(GraderAPIClient):
    """NGC (Numismatic Guaranty Company) API client"""

    def __init__(self, api_key=None):
        super().__init__('NGC', api_key)
        self.base_url = "https://www.ngccoin.com/certlookup"

    def lookup_certificate(self, cert_number):
        """Lookup NGC certificate number"""
        try:
            params = {'q': cert_number}
            response = requests.get(self.base_url, params=params, timeout=10)
            response.raise_for_status()

            return {
                'status': 'success',
                'data': response.json(),
                'url': f"https://www.ngccoin.com/certlookup/{cert_number}"
            }
        except requests.exceptions.RequestException as e:
            return {
                'status': 'failed',
                'error': str(e)
            }


class BeckettAPIClient(GraderAPIClient):
    """Beckett Grading Services API client"""

    def __init__(self, api_key=None):
        super().__init__('Beckett', api_key)
        self.base_url = "https://www.beckettgrading.com/certlookup"

    def lookup_certificate(self, cert_number):
        """Lookup Beckett certificate number"""
        try:
            params = {'cert': cert_number}
            response = requests.get(self.base_url, params=params, timeout=10)
            response.raise_for_status()

            return {
                'status': 'success',
                'data': response.json(),
                'url': f"https://www.beckettgrading.com/cert/{cert_number}"
            }
        except requests.exceptions.RequestException as e:
            return {
                'status': 'failed',
                'error': str(e)
            }


class EntropyAPIClient(GraderAPIClient):
    """Entrupy AI authentication API for luxury items"""

    def __init__(self, api_key=None):
        super().__init__('Entrupy', api_key)
        self.base_url = "https://api.entrupy.com/v1"

    def lookup_certificate(self, cert_number):
        """Verify luxury item authenticity with Entrupy AI"""
        try:
            endpoint = f"{self.base_url}/authentication/{cert_number}"
            headers = {'Authorization': f'Bearer {self.api_key}'} if self.api_key else {}

            response = requests.get(endpoint, headers=headers, timeout=10)
            response.raise_for_status()

            data = response.json()
            return {
                'status': 'success',
                'data': data,
                'confidence': data.get('confidence_score', 0),
                'url': f"https://www.entrupy.com/verify/{cert_number}"
            }
        except requests.exceptions.RequestException as e:
            return {
                'status': 'failed',
                'error': str(e)
            }


class SneakerAuthAPIClient(GraderAPIClient):
    """Sneaker authentication service client (StockX/GOAT model)"""

    def __init__(self, api_key=None):
        super().__init__('SneakerAuth', api_key)
        self.base_url = "https://api.sneakerauth.com/v1"

    def lookup_certificate(self, cert_number):
        """Verify sneaker authenticity"""
        try:
            endpoint = f"{self.base_url}/verify"
            headers = {'Authorization': f'Bearer {self.api_key}'} if self.api_key else {}
            payload = {'certificate_id': cert_number}

            response = requests.post(endpoint, json=payload, headers=headers, timeout=10)
            response.raise_for_status()

            data = response.json()
            return {
                'status': 'success',
                'data': data,
                'authentication': data.get('authentication_status', 'pending'),
                'url': f"https://www.sneakerauth.com/cert/{cert_number}"
            }
        except requests.exceptions.RequestException as e:
            return {
                'status': 'failed',
                'error': str(e)
            }


class WineAuthAPIClient(GraderAPIClient):
    """Wine authentication and provenance verification client"""

    def __init__(self, api_key=None):
        super().__init__('WineAuth', api_key)
        self.base_url = "https://api.wineauth.com/v1"

    def lookup_certificate(self, cert_number):
        """Verify wine authenticity and provenance"""
        try:
            endpoint = f"{self.base_url}/bottles/{cert_number}"
            headers = {'Authorization': f'Bearer {self.api_key}'} if self.api_key else {}

            response = requests.get(endpoint, headers=headers, timeout=10)
            response.raise_for_status()

            data = response.json()
            return {
                'status': 'success',
                'data': data,
                'provenance': data.get('provenance_verified', False),
                'url': f"https://www.wineauth.com/bottle/{cert_number}"
            }
        except requests.exceptions.RequestException as e:
            return {
                'status': 'failed',
                'error': str(e)
            }


# Mapping of graders to their API clients
GRADER_CLIENTS = {
    'PSA': PSAAPIClient,
    'PCGS': PCGSAPIClient,
    'NGC': NGCAPIClient,
    'Beckett': BeckettAPIClient,
    'BGS': BeckettAPIClient,  # Beckett Grading Services
    'CGC': None,  # CGC API not yet implemented
    'SGC': None,  # SGC API not yet implemented
    'Entrupy': EntropyAPIClient,  # Luxury handbag/accessory authentication
    'SneakerAuth': SneakerAuthAPIClient,  # Sneaker authentication
    'WineAuth': WineAuthAPIClient,  # Wine provenance verification
}


class CollectibleVerificationService:
    """Main service for handling collectible verification"""

    @staticmethod
    def initialize_graders():
        """Initialize supported graders in database"""
        graders_data = [
            # Tier 1: Graded collectibles
            {
                'name': 'PSA',
                'cert_types': json.dumps(['trading_card', 'autograph', 'comic']),
                'lookup_method': 'cert_number',
                'lookup_instructions': 'Enter 7-digit PSA certification number'
            },
            {
                'name': 'PCGS',
                'cert_types': json.dumps(['coin', 'banknote']),
                'lookup_method': 'cert_number',
                'lookup_instructions': 'Enter PCGS certification number'
            },
            {
                'name': 'NGC',
                'cert_types': json.dumps(['coin']),
                'lookup_method': 'cert_number',
                'lookup_instructions': 'Enter NGC certification number'
            },
            {
                'name': 'Beckett',
                'cert_types': json.dumps(['trading_card', 'autograph']),
                'lookup_method': 'cert_number',
                'lookup_instructions': 'Enter Beckett certification number'
            },
            {
                'name': 'CGC',
                'cert_types': json.dumps(['comic', 'trading_card']),
                'lookup_method': 'cert_number',
                'lookup_instructions': 'Enter CGC certification number'
            },
            # Tier 2: Luxury and modern collectibles
            {
                'name': 'Entrupy',
                'cert_types': json.dumps(['luxury_handbag', 'luxury_accessory']),
                'lookup_method': 'certificate_id',
                'lookup_instructions': 'Enter Entrupy authentication certificate ID'
            },
            {
                'name': 'SneakerAuth',
                'cert_types': json.dumps(['sneaker']),
                'lookup_method': 'certificate_id',
                'lookup_instructions': 'Enter SneakerAuth verification certificate ID'
            },
            {
                'name': 'WineAuth',
                'cert_types': json.dumps(['wine', 'spirits']),
                'lookup_method': 'certificate_id',
                'lookup_instructions': 'Enter WineAuth provenance certificate ID'
            },
        ]

        for grader_data in graders_data:
            existing = SupportedGrader.query.filter_by(name=grader_data['name']).first()
            if not existing:
                grader = SupportedGrader(**grader_data)
                db.session.add(grader)

        db.session.commit()

    @staticmethod
    def verify_certificate(product_id, collectible_type, grader, certificate_number, grade=None, year=None):
        """Main verification workflow"""

        # Check for duplicate certificates
        existing_cert = CollectibleVerification.query.filter_by(
            certificate_number=certificate_number,
            grader=grader
        ).first()

        if existing_cert and existing_cert.product_id != product_id:
            return {
                'status': 'duplicate_detected',
                'message': f'Certificate {certificate_number} already used in product #{existing_cert.product_id}',
                'previous_product_id': existing_cert.product_id
            }

        # Create verification record
        verification = CollectibleVerification.query.filter_by(product_id=product_id).first()
        if not verification:
            verification = CollectibleVerification(product_id=product_id)

        verification.collectible_type = collectible_type
        verification.grader = grader
        verification.certificate_number = certificate_number
        verification.grade = grade
        verification.year = year
        verification.verification_status = 'pending'

        db.session.add(verification)
        db.session.commit()

        # Attempt API lookup
        api_result = CollectibleVerificationService.lookup_with_api(grader, certificate_number)

        # Log the verification attempt
        log_entry = VerificationLog(
            collectible_id=verification.id,
            action='api_lookup',
            status=api_result['status'],
            details=json.dumps(api_result),
            performed_by='system'
        )
        db.session.add(log_entry)

        # Update verification record based on API result
        if api_result['status'] == 'success':
            verification.verification_status = 'verified'
            verification.verification_date = datetime.utcnow()
            verification.verified_by = 'api'
            verification.grader_response = json.dumps(api_result.get('data', {}))
            verification.grader_cert_url = api_result.get('url')
        else:
            verification.verification_status = 'manual_review'
            # Mark for manual review if API fails

        db.session.commit()

        return {
            'status': 'success',
            'verification_id': verification.id,
            'api_result': api_result,
            'message': 'Certificate submitted for verification'
        }

    @staticmethod
    def lookup_with_api(grader, certificate_number):
        """Attempt to verify certificate with grader API"""

        client_class = GRADER_CLIENTS.get(grader)
        if not client_class:
            return {
                'status': 'api_not_implemented',
                'message': f'API integration for {grader} not yet implemented'
            }

        try:
            client = client_class()
            result = client.lookup_certificate(certificate_number)
            return result
        except Exception as e:
            return {
                'status': 'api_error',
                'error': str(e),
                'message': f'Error connecting to {grader} API'
            }

    @staticmethod
    def verify_photos(verification_id, photo_urls):
        """Mark photos as uploaded and set for manual review"""
        verification = CollectibleVerification.query.get(verification_id)
        if not verification:
            return {'status': 'failed', 'message': 'Verification not found'}

        verification.slab_photo_urls = json.dumps(photo_urls)
        verification.updated_at = datetime.utcnow()

        db.session.commit()

        # Log photo upload
        log_entry = VerificationLog(
            collectible_id=verification.id,
            action='photo_upload',
            status='success',
            details=json.dumps({'photo_count': len(photo_urls)}),
            performed_by='system'
        )
        db.session.add(log_entry)
        db.session.commit()

        return {'status': 'success', 'message': 'Photos uploaded for verification'}

    @staticmethod
    def approve_manual_verification(verification_id, admin_user):
        """Admin manually approves verification"""
        verification = CollectibleVerification.query.get(verification_id)
        if not verification:
            return {'status': 'failed', 'message': 'Verification not found'}

        verification.verification_status = 'verified'
        verification.verification_date = datetime.utcnow()
        verification.verified_by = admin_user
        verification.photos_verified = True
        verification.photos_verified_by = admin_user
        verification.photos_verified_date = datetime.utcnow()

        db.session.commit()

        log_entry = VerificationLog(
            collectible_id=verification.id,
            action='manual_verification',
            status='success',
            details='Admin approved',
            performed_by=admin_user
        )
        db.session.add(log_entry)
        db.session.commit()

        return {'status': 'success', 'message': 'Verification approved'}

    @staticmethod
    def get_verification_status(product_id):
        """Get verification status for a product"""
        verification = CollectibleVerification.query.filter_by(product_id=product_id).first()
        if not verification:
            return {'status': 'not_found'}

        return {
            'status': verification.verification_status,
            'collectible_type': verification.collectible_type,
            'grader': verification.grader,
            'certificate_number': verification.certificate_number,
            'grade': verification.grade,
            'verified_date': verification.verification_date.isoformat() if verification.verification_date else None,
            'cert_url': verification.grader_cert_url
        }
