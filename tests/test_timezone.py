"""Times are stored in UTC but typed and shown in IST. These run with the site zone switched to IST (the other tests pin UTC)."""
import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app import timeutil
from app.config import Config
from app.models import Product, utcnow

from .test_buyer import cats, make_auction  # noqa: F401  (cats is a fixture)
from .test_payments import client_for
from .test_seller import FMT, form_data, post_new

IST = timedelta(hours=5, minutes=30)
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def ist(app):
    app.config["TZ_NAME"], app.config["TZ_OFFSET_MINUTES"] = "IST", 330
    return app


def local_now():
    return utcnow() + IST


def test_the_default_zone_is_ist_and_configurable():
    assert Config.TZ_NAME == "IST" and Config.TZ_OFFSET_MINUTES == 330
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "APP_TZ_NAME=IST" in text and "APP_TZ_OFFSET_MINUTES=330" in text


def test_conversion_round_trips_and_formats_with_the_zone_name(ist):
    utc = datetime(2026, 10, 4, 7, 30)
    assert timeutil.to_local(utc) == datetime(2026, 10, 4, 13, 0)
    assert timeutil.from_local(timeutil.to_local(utc)) == utc
    assert timeutil.fmt(utc) == "04 Oct 2026 13:00 IST"
    assert timeutil.fmt(datetime(2026, 10, 4, 20, 0)) == "05 Oct 2026 01:30 IST"  # crosses midnight
    assert timeutil.fmt(None) == "" and timeutil.to_local(None) is None


def test_one_pm_typed_by_a_seller_is_one_pm_ist_not_one_pm_utc(ist, users, cats):  # noqa: F811
    """The reported bug: a start of 1pm showed '5 hours to wait' because 13:00 was taken as UTC."""
    c = client_for(ist, "seller@t.test")
    start = (local_now() + timedelta(hours=3)).replace(second=0, microsecond=0)
    r = post_new(c, cats["Books"], auction_start=start.strftime(FMT), auction_end=(start + timedelta(days=1)).strftime(FMT))
    assert r.status_code == 302
    p = Product.query.one()
    assert p.auction_start == start - IST  # stored as UTC
    assert p.auction_end == start + timedelta(days=1) - IST
    page = c.get(f"/seller/products/{p.id}").data.decode()
    assert start.strftime("%d %b %Y %H:%M") + " IST" in page  # shown back exactly as typed
    assert "UTC" not in page.split("Starts", 1)[1][:200]


def test_the_edit_form_is_prefilled_in_ist(ist, users, cats):  # noqa: F811
    c = client_for(ist, "seller@t.test")
    start = (local_now() + timedelta(hours=4)).replace(second=0, microsecond=0)
    post_new(c, cats["Books"], auction_start=start.strftime(FMT), auction_end=(start + timedelta(days=2)).strftime(FMT))
    p = Product.query.one()
    html = c.get(f"/seller/products/{p.id}/edit").data.decode()
    assert f'value="{start.strftime(FMT)}"' in html
    assert f'value="{(start + timedelta(days=2)).strftime(FMT)}"' in html


def test_saving_the_edit_form_unchanged_does_not_shift_the_times(ist, users, cats):  # noqa: F811
    c = client_for(ist, "seller@t.test")
    start = (local_now() + timedelta(hours=4)).replace(second=0, microsecond=0)
    end = start + timedelta(days=2)
    post_new(c, cats["Books"], auction_start=start.strftime(FMT), auction_end=end.strftime(FMT))
    p = Product.query.one()
    for _ in range(3):  # each round trip would drift by 5h30 if a conversion were missing or doubled
        c.post(f"/seller/products/{p.id}/edit", data=form_data(cats["Books"], auction_start=start.strftime(FMT), auction_end=end.strftime(FMT)),
               content_type="multipart/form-data")
    from app.extensions import db
    db.session.expire_all()
    assert db.session.get(Product, p.id).auction_start == start - IST


def test_past_start_is_judged_in_ist(ist, users, cats):  # noqa: F811
    c = client_for(ist, "seller@t.test")
    past = (local_now() - timedelta(hours=1)).replace(second=0, microsecond=0)  # one hour ago in IST
    r = post_new(c, cats["Books"], auction_start=past.strftime(FMT), auction_end=(past + timedelta(days=1)).strftime(FMT))
    assert r.status_code == 200 and b"cannot be in the past" in r.data and Product.query.count() == 0
    # the same wall-clock digits read as UTC would have been 5.5 hours in the past too, but a UTC clock reading is now far in the past here:
    utc_wall = utcnow().replace(second=0, microsecond=0)
    r = post_new(c, cats["Books"], auction_start=utc_wall.strftime(FMT), auction_end=(utc_wall + timedelta(days=1)).strftime(FMT))
    assert r.status_code == 200 and Product.query.count() == 0


def test_the_form_says_which_zone_to_use(ist, users):
    html = client_for(ist, "seller@t.test").get("/seller/products/new").data.decode()
    assert "Auction start (IST)" in html and "Auction end (IST)" in html and "Times are in IST." in html
    assert "(UTC)" not in html


def test_auction_pages_and_cards_show_ist(ist, users, cats):  # noqa: F811
    a = make_auction(users["seller"], cats["Books"], "Lamp", 100, hours_left=5)
    page = client_for(ist, "buyer@t.test").get(f"/auctions/{a.id}").data.decode()
    assert timeutil.fmt(a.end_time) in page and "IST" in page
    assert re.search(r'data-end="[^"]+Z?"', page)  # the countdown itself still runs on absolute UTC instants
    s = make_auction(users["seller"], cats["Sports"], "Soon", 100, status="scheduled")
    home = client_for(ist, "buyer@t.test").get("/auctions/?status=all").data.decode()
    assert "Starts " + timeutil.fmt(s.start_time) in home


def test_the_countdown_data_stays_utc_so_it_is_correct_whatever_the_display_zone(ist, users, cats):  # noqa: F811
    a = make_auction(users["seller"], cats["Books"], "Clock", 100, hours_left=2)
    page = client_for(ist, "buyer@t.test").get(f"/auctions/{a.id}").data.decode()
    end_attr = re.search(r'data-end="([^"]+)"', page).group(1)
    now_attr = re.search(r'data-now="([^"]+)"', page).group(1)
    assert end_attr.endswith("Z") and now_attr.endswith("Z")
    end = datetime.fromisoformat(end_attr.replace("Z", "+00:00"))
    now = datetime.fromisoformat(now_attr.replace("Z", "+00:00"))
    assert timedelta(hours=1, minutes=58) < end - now < timedelta(hours=2, minutes=1)  # two hours left, not 7h30 or -3h30


def test_the_browser_script_formats_in_the_site_zone(ist, users):
    html = client_for(ist, "buyer@t.test").get("/").data.decode()
    assert re.search(r'<meta name="app-tz" content="IST" data-offset="330">', html)
    js = (ROOT / "app" / "static" / "js" / "auction.js").read_text(encoding="utf-8")
    assert "tzOffset" in js and "app-tz" in js and '+ " UTC"' not in js


def test_invoice_times_print_in_ist(ist):
    from app.services.invoice_service import _dt
    assert _dt(datetime(2026, 10, 4, 7, 30)) == "04 Oct 2026, 13:00 IST"
    assert _dt(None) == "-"


def test_no_template_still_uses_the_old_utc_filter():
    leftovers = [str(p) for p in (ROOT / "app" / "templates").rglob("*.html") if "|utc" in p.read_text(encoding="utf-8")]
    assert leftovers == []


# ---- reports and analytics --------------------------------------------------------------------------------------------
@pytest.fixture
def paid_late_evening_utc(ist, users, cats):  # noqa: F811
    """A paid purchase stamped 2026-10-04 20:00 UTC, which is already 01:30 on 5 October in IST."""
    import io

    import openpyxl  # noqa: F401  (imported here so a missing dependency fails with a clear test error)
    from app.extensions import db
    from app.models import Payment

    from .test_payments import card, pay, won
    a = won(users, cats, amount="500")
    pay(client_for(ist, "buyer@t.test"), a, "card", card())
    p = db.session.query(Payment).one()
    p.created_at = p.payment_date = datetime(2026, 10, 4, 20, 0)
    db.session.commit()
    return p


def run_report(key, args, now=datetime(2026, 10, 15, 12, 0)):
    from app.services import report_service as rs
    report = rs.REPORTS[key]
    params, errors = rs.parse_params(report, args, now)
    return report, params, errors, rs.run(report, params)


def test_a_report_day_is_an_ist_day(paid_late_evening_utc):
    _, params, _, data = run_report("payments", {"from": "2026-10-05", "to": "2026-10-05"})
    assert params.start == datetime(2026, 10, 4, 18, 30) and params.end == datetime(2026, 10, 5, 18, 30)  # the UTC edges of that IST day
    assert len(data.rows) == 1  # 20:00 UTC on the 4th is on the 5th in IST
    _, _, _, data = run_report("payments", {"from": "2026-10-04", "to": "2026-10-04"})
    assert data.rows == []  # and not on the 4th


def test_the_range_is_shown_back_as_typed_and_today_follows_ist(paid_late_evening_utc):
    from app.services import report_export as rx
    report, params, _, _ = run_report("payments", {"from": "2026-10-05", "to": "2026-10-06"})
    assert params.first_day.isoformat() == "2026-10-05" and params.last_day.isoformat() == "2026-10-06"
    assert "Period: 2026-10-05 to 2026-10-06" in rx.describe_params(report, params)
    _, params, _, _ = run_report("payments", {}, now=datetime(2026, 10, 4, 20, 0))  # default range ends "today"
    assert params.last_day.isoformat() == "2026-10-05"  # it is already the 5th in IST


def test_times_and_column_names_in_a_report_use_ist(paid_late_evening_utc):
    from app.services import report_export as rx
    report, params, _, data = run_report("payments", {"from": "2026-10-05", "to": "2026-10-05"})
    labels = [c.display_label for c in report.columns]
    assert "Created (IST)" in labels and "Paid (IST)" in labels and not any("UTC" in x for x in labels)
    assert rx.fmt("datetime", data.rows[0][10]) == "2026-10-05 01:30"


def test_the_excel_export_holds_ist_times_and_says_so(paid_late_evening_utc):
    import io

    import openpyxl
    from app.services import report_export as rx
    report, params, _, data = run_report("payments", {"from": "2026-10-05", "to": "2026-10-05"})
    ws = openpyxl.load_workbook(io.BytesIO(rx.render_xlsx(report, data, params, datetime(2026, 10, 15, 6, 30)))).active
    assert "Generated 2026-10-15 12:00 IST" in ws["A3"].value  # 06:30 UTC is 12:00 IST
    headers = {c.value: c.column for c in ws[5]}
    assert "Created (IST)" in headers
    assert ws.cell(6, headers["Created (IST)"]).value == datetime(2026, 10, 5, 1, 30)
    assert rx.filename(report, "xlsx", datetime(2026, 10, 15, 20, 0)).endswith("20261016.xlsx")  # the file name carries the IST date


def test_the_pdf_export_says_ist(paid_late_evening_utc):
    import io

    from pypdf import PdfReader

    from app.services import report_export as rx
    report, params, _, data = run_report("payments", {"from": "2026-10-05", "to": "2026-10-05"})
    text = " ".join(page.extract_text() for page in PdfReader(io.BytesIO(rx.render_pdf(report, data, params, datetime(2026, 10, 15, 6, 30)))).pages)
    assert "Generated 2026-10-15 12:00 IST" in text and "(UTC)" not in text and "2026-10-05 01:30" in text


def test_the_revenue_report_groups_by_ist_day(paid_late_evening_utc):
    _, _, _, data = run_report("revenue", {"from": "2026-10-01", "to": "2026-10-31"})
    assert [r[0].isoformat() for r in data.rows] == ["2026-10-05"]  # not the 4th


def test_report_pages_show_ist_everywhere(ist, users, paid_late_evening_utc):
    admin = client_for(ist, "admin@t.test")
    index = admin.get("/admin/reports").data.decode()
    assert "Times are in IST" in index and "UTC" not in index.split("Times are in", 1)[1][:30]
    page = admin.get("/admin/reports/payments?from=2026-10-05&to=2026-10-05").data.decode()
    assert "Created (IST)" in page and "2026-10-05 01:30" in page and 'value="2026-10-05"' in page and "(UTC)" not in page
    assert "Showing" not in page and "No data for these filters" not in page


def test_analytics_months_follow_ist(ist, users, cats):  # noqa: F811
    """A payment at 20:00 UTC on 30 September is already October in IST, so it belongs to October's bar."""
    from app.extensions import db
    from app.models import Payment
    from app.services import analytics_service

    from .test_payments import card, pay, won
    a = won(users, cats, amount="500")
    pay(client_for(ist, "buyer@t.test"), a, "card", card())
    p = db.session.query(Payment).one()
    p.payment_date = datetime(2026, 9, 30, 20, 0)
    db.session.commit()
    out = analytics_service.build(months=3, now=datetime(2026, 10, 15, 12, 0))
    revenue = dict(zip(out["labels"], out["revenue"]["simulated"]))
    assert revenue["Oct 2026"] == 500.0 and revenue["Sep 2026"] == 0.0


def test_analytics_months_still_use_utc_when_the_zone_is_utc(app, users, cats):  # noqa: F811
    from app.extensions import db
    from app.models import Payment
    from app.services import analytics_service

    from .test_payments import card, pay, won
    a = won(users, cats, amount="500")
    pay(client_for(app, "buyer@t.test"), a, "card", card())
    p = db.session.query(Payment).one()
    p.payment_date = datetime(2026, 9, 30, 20, 0)
    db.session.commit()
    out = analytics_service.build(months=3, now=datetime(2026, 10, 15, 12, 0))
    assert dict(zip(out["labels"], out["revenue"]["simulated"]))["Sep 2026"] == 500.0  # test config is UTC: unchanged behaviour
