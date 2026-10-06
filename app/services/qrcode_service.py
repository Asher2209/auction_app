"""QR code generation and management for trading cards"""

import hashlib
import qrcode
from pathlib import Path
from io import BytesIO
import base64
from flask import current_app
from ..models import CollectibleCard


def generate_platform_card_id(card_id: int) -> str:
    """Generate unique platform card ID in format CARD-XXXXXX"""
    return f"CARD-{card_id:06d}"


def generate_qr_code_svg(platform_card_id: str, include_metadata: bool = False) -> str:
    """
    Generate QR code for a card in SVG format (can be displayed in HTML).
    
    Args:
        platform_card_id: The card's platform ID (e.g., CARD-000001)
        include_metadata: Whether to include card metadata in the QR data
    
    Returns:
        SVG string representation of the QR code
    """
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=2,
    )
    
    # QR code links to public card verification page
    qr_url = f"/collectible/verify/{platform_card_id}"
    qr.add_data(qr_url)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    
    # Convert to SVG
    buffer = BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)
    
    # Return as SVG (we'll use qrcode library to generate SVG directly)
    qr_svg = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=2,
    )
    qr_svg.add_data(qr_url)
    qr_svg.make(fit=True)
    
    # Generate SVG manually for cleaner output
    qr_data = qr_svg.get_matrix()
    qr_size = len(qr_data)
    box_size = 10
    total_size = qr_size * box_size + 40  # padding
    
    svg_lines = [
        f'<svg width="{total_size}" height="{total_size}" xmlns="http://www.w3.org/2000/svg">',
        '<rect width="100%" height="100%" fill="white"/>',
    ]
    
    for y, row in enumerate(qr_data):
        for x, is_dark in enumerate(row):
            if is_dark:
                rect_x = x * box_size + 20
                rect_y = y * box_size + 20
                svg_lines.append(f'<rect x="{rect_x}" y="{rect_y}" width="{box_size}" height="{box_size}" fill="black"/>')
    
    svg_lines.append('</svg>')
    
    return '\n'.join(svg_lines)


def save_qr_code_to_file(platform_card_id: str, card_id: int) -> str:
    """
    Save QR code as PNG file to static directory.
    
    Returns:
        Path relative to static folder (for use in <img src>)
    """
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=2,
    )
    
    qr_url = f"/collectible/verify/{platform_card_id}"
    qr.add_data(qr_url)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    
    # Create qrcodes directory if needed
    qrcode_dir = Path(current_app.static_folder) / "qrcodes"
    qrcode_dir.mkdir(parents=True, exist_ok=True)
    
    # Save with card ID as filename
    filename = f"card_{card_id}_{platform_card_id}.png"
    filepath = qrcode_dir / filename
    
    img.save(filepath)
    
    return f"qrcodes/{filename}"


def get_qr_code_html(platform_card_id: str) -> str:
    """Get QR code as inline SVG HTML"""
    return generate_qr_code_svg(platform_card_id)
