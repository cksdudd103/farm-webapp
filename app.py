# -*- coding: utf-8 -*-
"""
스마트 영농관리 웹앱 (Smart Farm Management Web App)
Flask + SQLAlchemy + Flask-Login 기반 백엔드
"""
import json
import os
import random
import string
import uuid
from datetime import datetime, date, timedelta

import requests
from bs4 import BeautifulSoup
try:
    import google.generativeai as genai
except ImportError:  # pragma: no cover - optional dependency
    genai = None
from flask import Flask, render_template, request, jsonify, session, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    login_required, current_user
)
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_EXT = {"png", "jpg", "jpeg", "gif", "webp"}

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "smart-farm-secret-key-change-in-production")

_db_url = os.environ.get("DATABASE_URL", "sqlite:///" + os.path.join(BASE_DIR, "farm.db"))
if _db_url.startswith("postgres://"):
    _db_url = _db_url.replace("postgres://", "postgresql://", 1)
if _db_url.startswith("postgresql://"):
    # Use the psycopg (v3) driver, which ships prebuilt wheels for modern
    # Python versions (psycopg2-binary lacks compatible wheels on some hosts)
    _db_url = _db_url.replace("postgresql://", "postgresql+psycopg://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = _db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024  # 8MB

# 프론트엔드(farm-android-pymx.onrender.com)와 백엔드(farm-webapp-rezy.onrender.com)가
# 서로 다른 오리진의 HTTPS 서비스이므로, 세션 쿠키가 cross-site 요청에도 전달되도록 설정
app.config["SESSION_COOKIE_SAMESITE"] = "None"
app.config["SESSION_COOKIE_SECURE"] = True
app.config["REMEMBER_COOKIE_SAMESITE"] = "None"
app.config["REMEMBER_COOKIE_SECURE"] = True

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if GEMINI_API_KEY and genai:
    genai.configure(api_key=GEMINI_API_KEY)


def public_image_url(image_path):
    if not image_path:
        return None
    if image_path.startswith("http://") or image_path.startswith("https://"):
        return image_path
    path = image_path.lstrip("/")
    host = os.environ.get("BACKEND_PUBLIC_URL", request.host_url.rstrip("/"))
    return f"{host}/{path}"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# 안드로이드 앱 등 외부(모든 origin)에서 API를 호출할 수 있도록 CORS 허용
CORS(app, supports_credentials=True, resources={r"/*": {"origins": "*"}})


# ----------------------------------------------------------------------
# 정적 파일 서빙 (업로드 이미지)
# ----------------------------------------------------------------------
@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login_page"


# ----------------------------------------------------------------------
# 모델 (Models)
# ----------------------------------------------------------------------
class User(db.Model, UserMixin):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default="farmer")  # admin / farmer
    phone = db.Column(db.String(30))
    farm_name = db.Column(db.String(120))
    region = db.Column(db.String(80))
    is_active_user = db.Column(db.Boolean, default=True)
    grade_id = db.Column(db.Integer, db.ForeignKey("grades.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw):
        return check_password_hash(self.password_hash, pw)

    def to_dict(self):
        sub = get_current_subscription(self.id)
        grade = db.session.get(Grade, self.grade_id) if self.grade_id else None
        return {
            "id": self.id, "name": self.name, "email": self.email,
            "role": self.role, "phone": self.phone, "farm_name": self.farm_name,
            "region": self.region, "is_active_user": self.is_active_user,
            "created_at": self.created_at.strftime("%Y-%m-%d") if self.created_at else None,
            "plan_code": sub["plan_code"], "plan_name": sub["plan_name"],
            "subscription_status": sub["status"], "subscription_expiry": sub["expiry_date"],
            "billing_cycle": sub["billing_cycle"], "is_waived": sub.get("is_waived", False),
            "grade_id": self.grade_id, "grade_code": grade.code if grade else "general",
            "grade_name": grade.name if grade else "일반회원",
            "grade_discount": grade.discount_percent if grade else 0,
            "grade_color": grade.color if grade else "#8a9a8a",
        }


class Plan(db.Model):
    __tablename__ = "plans"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(30), unique=True, nullable=False)
    name = db.Column(db.String(60), nullable=False)
    price_monthly = db.Column(db.Integer, default=0)
    price_annual = db.Column(db.Integer, default=0)
    features = db.Column(db.Text)  # JSON 문자열 리스트
    is_active = db.Column(db.Boolean, default=True)
    display_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def get_features(self):
        try:
            return json.loads(self.features) if self.features else []
        except Exception:
            return []

    def set_features(self, feature_list):
        self.features = json.dumps(feature_list, ensure_ascii=False)

    def to_dict(self):
        return {
            "id": self.id, "code": self.code, "name": self.name,
            "price_monthly": self.price_monthly, "price_annual": self.price_annual,
            "features": self.get_features(), "is_active": self.is_active,
            "display_order": self.display_order,
            "created_at": self.created_at.strftime("%Y-%m-%d") if self.created_at else None
        }


class UserSubscription(db.Model):
    __tablename__ = "user_subscriptions"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    plan_id = db.Column(db.Integer, db.ForeignKey("plans.id"), nullable=False)
    billing_cycle = db.Column(db.String(10), default="monthly")  # monthly / annual
    status = db.Column(db.String(20), default="active")  # active/cancelled/expired
    start_date = db.Column(db.String(20))
    expiry_date = db.Column(db.String(20))
    is_waived = db.Column(db.Boolean, default=False)  # 관리자 요금제 면제 여부
    promo_code = db.Column(db.String(40), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        plan = db.session.get(Plan, self.plan_id)
        return {
            "id": self.id, "user_id": self.user_id, "plan_id": self.plan_id,
            "plan_name": plan.name if plan else None,
            "billing_cycle": self.billing_cycle, "status": self.status,
            "start_date": self.start_date, "expiry_date": self.expiry_date,
            "is_waived": self.is_waived, "promo_code": self.promo_code,
            "created_at": self.created_at.strftime("%Y-%m-%d") if self.created_at else None
        }


class Grade(db.Model):
    __tablename__ = "grades"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(30), unique=True, nullable=False)
    name = db.Column(db.String(60), nullable=False)
    discount_percent = db.Column(db.Integer, default=0)  # 요금제 할인율(%)
    min_spend = db.Column(db.Integer, default=0)  # 등급 산정 기준 참고값(원)
    color = db.Column(db.String(20), default="#6b746b")
    display_order = db.Column(db.Integer, default=0)
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id, "code": self.code, "name": self.name,
            "discount_percent": self.discount_percent, "min_spend": self.min_spend,
            "color": self.color, "display_order": self.display_order,
            "description": self.description,
        }


class PromoCode(db.Model):
    __tablename__ = "promo_codes"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(40), unique=True, nullable=False)
    discount_percent = db.Column(db.Integer, default=0)
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    max_uses = db.Column(db.Integer, default=0)  # 0 = 무제한
    used_count = db.Column(db.Integer, default=0)
    expiry_date = db.Column(db.String(20), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id, "code": self.code, "discount_percent": self.discount_percent,
            "description": self.description, "is_active": self.is_active,
            "max_uses": self.max_uses, "used_count": self.used_count,
            "expiry_date": self.expiry_date,
            "created_at": self.created_at.strftime("%Y-%m-%d") if self.created_at else None
        }

    def is_valid(self):
        if not self.is_active:
            return False
        if self.expiry_date and date.fromisoformat(self.expiry_date) < date.today():
            return False
        if self.max_uses and self.used_count >= self.max_uses:
            return False
        return True


class PlanChangeLog(db.Model):
    __tablename__ = "plan_change_logs"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    from_plan = db.Column(db.String(60))
    to_plan = db.Column(db.String(60))
    action = db.Column(db.String(20))  # upgrade/downgrade/waiver/admin_change
    detail = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        user = db.session.get(User, self.user_id)
        return {
            "id": self.id, "user_id": self.user_id,
            "user_name": user.name if user else "알수없음",
            "from_plan": self.from_plan, "to_plan": self.to_plan,
            "action": self.action, "detail": self.detail,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M") if self.created_at else None
        }


class Link(db.Model):
    __tablename__ = "links"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    url = db.Column(db.String(400), nullable=False)
    category = db.Column(db.String(40), default="공공기관")
    description = db.Column(db.Text)
    display_order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id, "title": self.title, "url": self.url,
            "category": self.category, "description": self.description,
            "display_order": self.display_order,
        }


class AdminActivityLog(db.Model):
    __tablename__ = "admin_activity_logs"
    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    action = db.Column(db.String(60), nullable=False)
    target_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    detail = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        admin = db.session.get(User, self.admin_id)
        target = db.session.get(User, self.target_user_id) if self.target_user_id else None
        return {
            "id": self.id, "admin_id": self.admin_id,
            "admin_name": admin.name if admin else "알수없음",
            "action": self.action,
            "target_user_id": self.target_user_id,
            "target_user_name": target.name if target else None,
            "detail": self.detail,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M") if self.created_at else None
        }


class Crop(db.Model):
    __tablename__ = "crops"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    name = db.Column(db.String(80), nullable=False)
    variety = db.Column(db.String(80))
    field_location = db.Column(db.String(120))
    area = db.Column(db.Float)
    planting_date = db.Column(db.String(20))
    expected_harvest_date = db.Column(db.String(20))
    status = db.Column(db.String(20), default="재배중")  # 재배중/수확완료/휴경
    memo = db.Column(db.Text)
    image = db.Column(db.String(255))
    is_public = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id, "user_id": self.user_id, "name": self.name,
            "variety": self.variety, "field_location": self.field_location,
            "area": self.area, "planting_date": self.planting_date,
            "expected_harvest_date": self.expected_harvest_date,
            "status": self.status, "memo": self.memo,
            "image": public_image_url(self.image),
            "is_public": self.is_public,
            "owner_name": owner.name if owner else None,
            "created_at": self.created_at.strftime("%Y-%m-%d") if self.created_at else None
        }


class Journal(db.Model):
    __tablename__ = "journals"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    crop_id = db.Column(db.Integer, db.ForeignKey("crops.id"), nullable=True)
    date = db.Column(db.String(20), nullable=False)
    work_type = db.Column(db.String(40))  # 파종/방제/시비/관수/수확/기타
    weather = db.Column(db.String(40))
    content = db.Column(db.Text)
    image = db.Column(db.String(255))
    is_public = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        crop = db.session.get(Crop, self.crop_id) if self.crop_id else None
        owner = db.session.get(User, self.user_id)
        return {
            "id": self.id, "user_id": self.user_id, "crop_id": self.crop_id,
            "crop_name": crop.name if crop else None,
            "date": self.date, "work_type": self.work_type, "weather": self.weather,
            "content": self.content, "image": public_image_url(self.image),
            "is_public": self.is_public,
            "owner_name": owner.name if owner else None,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M") if self.created_at else None
        }


class Task(db.Model):
    __tablename__ = "tasks"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    crop_id = db.Column(db.Integer, db.ForeignKey("crops.id"), nullable=True)
    title = db.Column(db.String(120), nullable=False)
    memo = db.Column(db.Text)
    due_date = db.Column(db.String(20))
    priority = db.Column(db.String(10), default="보통")  # 높음/보통/낮음
    status = db.Column(db.String(20), default="예정")  # 예정/진행중/완료
    is_public = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        crop = db.session.get(Crop, self.crop_id) if self.crop_id else None
        owner = db.session.get(User, self.user_id)
        return {
            "id": self.id, "user_id": self.user_id, "crop_id": self.crop_id,
            "crop_name": crop.name if crop else None,
            "title": self.title, "memo": self.memo, "due_date": self.due_date,
            "priority": self.priority, "status": self.status,
            "is_public": self.is_public,
            "owner_name": owner.name if owner else None,
            "created_at": self.created_at.strftime("%Y-%m-%d") if self.created_at else None
        }


class Inventory(db.Model):
    __tablename__ = "inventory"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    category = db.Column(db.String(40))  # 종자/비료/농약/농자재/기타
    quantity = db.Column(db.Float, default=0)
    unit = db.Column(db.String(20))
    location = db.Column(db.String(120))
    expiry_date = db.Column(db.String(20))
    memo = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id, "user_id": self.user_id, "name": self.name,
            "category": self.category, "quantity": self.quantity, "unit": self.unit,
            "location": self.location, "expiry_date": self.expiry_date, "memo": self.memo,
            "created_at": self.created_at.strftime("%Y-%m-%d") if self.created_at else None
        }


class Shipment(db.Model):
    __tablename__ = "shipments"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    crop_id = db.Column(db.Integer, db.ForeignKey("crops.id"), nullable=True)
    buyer = db.Column(db.String(120))
    quantity = db.Column(db.Float)
    unit = db.Column(db.String(20))
    unit_price = db.Column(db.Float)
    shipment_date = db.Column(db.String(20))
    status = db.Column(db.String(20), default="예정")  # 예정/출하완료/정산완료
    memo = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        crop = db.session.get(Crop, self.crop_id) if self.crop_id else None
        total = (self.quantity or 0) * (self.unit_price or 0)
        return {
            "id": self.id, "user_id": self.user_id, "crop_id": self.crop_id,
            "crop_name": crop.name if crop else None,
            "buyer": self.buyer, "quantity": self.quantity, "unit": self.unit,
            "unit_price": self.unit_price, "total_price": total,
            "shipment_date": self.shipment_date, "status": self.status, "memo": self.memo,
            "created_at": self.created_at.strftime("%Y-%m-%d") if self.created_at else None
        }


class Post(db.Model):
    __tablename__ = "posts"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    category = db.Column(db.String(40), default="자유")  # 공지/자유/질문/판매/정보공유
    title = db.Column(db.String(150), nullable=False)
    content = db.Column(db.Text)
    image = db.Column(db.String(255))
    views = db.Column(db.Integer, default=0)
    is_pinned = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        author = db.session.get(User, self.user_id)
        return {
            "id": self.id, "user_id": self.user_id,
            "author_name": author.name if author else "알수없음",
            "category": self.category, "title": self.title, "content": self.content,
            "image": public_image_url(self.image), "views": self.views, "is_pinned": self.is_pinned,
            "has_attachment": bool(self.image),
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M") if self.created_at else None,
            "created_date": self.created_at.strftime("%Y-%m-%d") if self.created_at else None
        }


class Diagnosis(db.Model):
    __tablename__ = "diagnoses"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    crop_name = db.Column(db.String(80))
    image = db.Column(db.String(255))
    disease_name = db.Column(db.String(120))
    confidence = db.Column(db.Float)
    severity = db.Column(db.String(20))
    advice = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id, "user_id": self.user_id, "crop_name": self.crop_name,
            "image": public_image_url(self.image), "disease_name": self.disease_name,
            "confidence": self.confidence, "severity": self.severity,
            "advice": self.advice,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M") if self.created_at else None
        }


class RdaNotice(db.Model):
    __tablename__ = "rda_notices"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text)
    category = db.Column(db.String(40), default="공지")
    notice_date = db.Column(db.String(20))
    source_url = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id, "title": self.title, "content": self.content,
            "category": self.category, "notice_date": self.notice_date,
            "source_url": self.source_url,
        }


class MarketPriceRecord(db.Model):
    __tablename__ = "market_price_records"
    id = db.Column(db.Integer, primary_key=True)
    regday = db.Column(db.String(10), nullable=False, index=True)  # YYYY-MM-DD
    name = db.Column(db.String(40), nullable=False)
    unit = db.Column(db.String(20))
    price = db.Column(db.Integer)
    change_pct = db.Column(db.Float, default=0.0)
    trend = db.Column(db.String(10), default="flat")
    source = db.Column(db.String(10), default="kamis")  # kamis | mock
    fetched_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint("regday", "name", name="uq_market_regday_name"),)

    def to_dict(self):
        return {
            "name": self.name, "unit": self.unit, "price": self.price,
            "change_pct": self.change_pct, "trend": self.trend, "source": self.source,
        }


class Payment(db.Model):
    __tablename__ = "payments"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    plan_id = db.Column(db.Integer, db.ForeignKey("plans.id"), nullable=False)
    order_id = db.Column(db.String(64), unique=True, nullable=False)
    order_name = db.Column(db.String(120))
    amount = db.Column(db.Integer, nullable=False)
    billing_cycle = db.Column(db.String(10), default="monthly")
    promo_code = db.Column(db.String(40))
    status = db.Column(db.String(20), default="pending")  # pending, approved, failed
    payment_key = db.Column(db.String(200))
    method = db.Column(db.String(30))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    approved_at = db.Column(db.DateTime)

    def to_dict(self):
        return {
            "id": self.id, "order_id": self.order_id, "order_name": self.order_name,
            "amount": self.amount, "billing_cycle": self.billing_cycle,
            "status": self.status, "method": self.method,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
        }


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# ----------------------------------------------------------------------
# 유틸 (Utilities)
# ----------------------------------------------------------------------
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT


def save_upload(file_storage):
    if not file_storage or file_storage.filename == "":
        return None
    if not allowed_file(file_storage.filename):
        return None
    ext = file_storage.filename.rsplit(".", 1)[1].lower()
    fname = f"{uuid.uuid4().hex}.{ext}"
    file_storage.save(os.path.join(UPLOAD_FOLDER, fname))
    return f"uploads/{fname}"


def is_admin():
    return current_user.is_authenticated and current_user.role == "admin"


def json_body():
    return request.get_json(silent=True) or {}


def get_current_subscription(user_id):
    """사용자의 현재 구독 정보를 반환 (없으면 무료 플랜 기본값)"""
    sub = (UserSubscription.query
           .filter_by(user_id=user_id)
           .order_by(UserSubscription.created_at.desc())
           .first())
    if not sub:
        free_plan = Plan.query.filter_by(code="free").first()
        return {
            "plan_id": free_plan.id if free_plan else None,
            "plan_code": "free", "plan_name": free_plan.name if free_plan else "무료",
            "status": "active", "expiry_date": None, "billing_cycle": "monthly",
            "is_waived": False,
        }
    plan = db.session.get(Plan, sub.plan_id)
    # 만료일이 지났으면 상태를 자동으로 만료 처리 (면제된 경우 제외)
    status = sub.status
    if status == "active" and sub.expiry_date and not sub.is_waived:
        try:
            if date.fromisoformat(sub.expiry_date) < date.today():
                status = "expired"
                sub.status = "expired"
                db.session.commit()
        except Exception:
            pass
    return {
        "plan_id": sub.plan_id, "plan_code": plan.code if plan else None,
        "plan_name": plan.name if plan else None, "status": status,
        "expiry_date": sub.expiry_date, "billing_cycle": sub.billing_cycle,
        "is_waived": sub.is_waived,
    }


def log_admin_activity(action, target_user_id=None, detail=None):
    log = AdminActivityLog(
        admin_id=current_user.id, action=action,
        target_user_id=target_user_id, detail=detail
    )
    db.session.add(log)
    db.session.commit()


def log_plan_change(user_id, from_plan, to_plan, action, detail=None):
    log = PlanChangeLog(user_id=user_id, from_plan=from_plan, to_plan=to_plan,
                         action=action, detail=detail)
    db.session.add(log)
    db.session.commit()


def apply_grade_discount(price, user):
    """사용자 등급 할인율을 적용한 가격 반환"""
    if not user or not user.grade_id:
        return price
    grade = db.session.get(Grade, user.grade_id)
    if not grade or not grade.discount_percent:
        return price
    return int(round(price * (100 - grade.discount_percent) / 100))


# ----------------------------------------------------------------------
# 페이지 라우트 (Page Routes)
# ----------------------------------------------------------------------
@app.route("/")
def login_page():
    if current_user.is_authenticated:
        return render_template("index.html", user=current_user)
    return render_template("login.html")


@app.route("/app")
@login_required
def app_page():
    return render_template("index.html", user=current_user)


@app.route("/manifest.json")
def manifest():
    return send_from_directory(BASE_DIR, "manifest.json")


@app.route("/service-worker.js")
def service_worker():
    return send_from_directory(BASE_DIR, "service-worker.js")


# ----------------------------------------------------------------------
# 인증 API (Auth API)
# ----------------------------------------------------------------------
@app.route("/api/register", methods=["POST"])
def api_register():
    data = json_body()
    name = data.get("name", "").strip()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    phone = data.get("phone", "").strip()
    farm_name = data.get("farm_name", "").strip()
    region = data.get("region", "").strip()
    admin_code = (data.get("admin_code") or "").strip()

    if not name or not email or not password:
        return jsonify({"ok": False, "msg": "이름, 이메일, 비밀번호는 필수입니다."}), 400
    if len(password) < 6:
        return jsonify({"ok": False, "msg": "비밀번호는 6자 이상이어야 합니다."}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({"ok": False, "msg": "이미 등록된 이메일입니다."}), 400

    role = "admin" if admin_code and admin_code == ADMIN_SIGNUP_CODE else "farmer"

    u = User(name=name, email=email, phone=phone, farm_name=farm_name,
             region=region, role=role, is_active_user=True)
    u.set_password(password)
    db.session.add(u)
    db.session.commit()
    login_user(u)
    return jsonify({"ok": True, "user": u.to_dict()})


@app.route("/api/find-id", methods=["POST"])
def api_find_id():
    data = json_body()
    name = data.get("name", "").strip()
    phone = data.get("phone", "").strip()
    if not name or not phone:
        return jsonify({"ok": False, "msg": "이름과 연락처를 입력해주세요."}), 400

    u = User.query.filter_by(name=name, phone=phone).first()
    if not u:
        return jsonify({"ok": False, "msg": "일치하는 회원 정보를 찾을 수 없습니다."}), 404

    local, _, domain = u.email.partition("@")
    if len(local) > 2:
        masked = local[:2] + "*" * (len(local) - 2)
    else:
        masked = local[:1] + "*" * (len(local) - 1)
    masked_email = f"{masked}@{domain}"
    return jsonify({"ok": True, "email": masked_email})


@app.route("/api/reset-password", methods=["POST"])
def api_reset_password():
    data = json_body()
    name = data.get("name", "").strip()
    email = data.get("email", "").strip().lower()
    phone = data.get("phone", "").strip()
    new_password = data.get("new_password", "")

    if not name or not email or not phone or not new_password:
        return jsonify({"ok": False, "msg": "모든 항목을 입력해주세요."}), 400
    if len(new_password) < 6:
        return jsonify({"ok": False, "msg": "비밀번호는 6자 이상이어야 합니다."}), 400

    u = User.query.filter_by(name=name, email=email, phone=phone).first()
    if not u:
        return jsonify({"ok": False, "msg": "일치하는 회원 정보를 찾을 수 없습니다."}), 404

    u.set_password(new_password)
    db.session.commit()
    return jsonify({"ok": True, "msg": "비밀번호가 재설정되었습니다."})


@app.route("/api/login", methods=["POST"])
def api_login():
    data = json_body()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    u = User.query.filter_by(email=email).first()
    if not u or not u.check_password(password):
        return jsonify({"ok": False, "msg": "이메일 또는 비밀번호가 올바르지 않습니다."}), 401
    if not u.is_active_user:
        return jsonify({"ok": False, "msg": "비활성화된 계정입니다. 관리자에게 문의하세요."}), 403
    login_user(u, remember=True)
    return jsonify({"ok": True, "user": u.to_dict()})


@app.route("/api/logout", methods=["POST"])
@login_required
def api_logout():
    logout_user()
    return jsonify({"ok": True})


@app.route("/api/me")
def api_me():
    if current_user.is_authenticated:
        return jsonify({"ok": True, "user": current_user.to_dict()})
    return jsonify({"ok": False}), 401


@app.route("/api/me", methods=["PUT"])
@login_required
def api_me_update():
    data = json_body()
    for field in ["name", "phone", "farm_name", "region"]:
        if field in data:
            setattr(current_user, field, data.get(field))
    if data.get("password"):
        if len(data.get("password")) < 6:
            return jsonify({"ok": False, "msg": "비밀번호는 6자 이상이어야 합니다."}), 400
        current_user.set_password(data.get("password"))
    db.session.commit()
    return jsonify({"ok": True, "user": current_user.to_dict()})


# ----------------------------------------------------------------------
# 사용자 관리 (Admin) API
# ----------------------------------------------------------------------
@app.route("/api/users", methods=["GET"])
@login_required
def api_users_list():
    if not is_admin():
        return jsonify({"ok": False, "msg": "권한이 없습니다."}), 403
    users = User.query.order_by(User.created_at.desc()).all()
    return jsonify({"ok": True, "data": [u.to_dict() for u in users]})


@app.route("/api/users/<int:uid>", methods=["PUT"])
@login_required
def api_users_update(uid):
    if not is_admin():
        return jsonify({"ok": False, "msg": "권한이 없습니다."}), 403
    u = User.query.get_or_404(uid)
    data = json_body()
    if "role" in data:
        u.role = data["role"]
    if "is_active_user" in data:
        u.is_active_user = bool(data["is_active_user"])
    if "name" in data:
        u.name = data["name"]
    if "grade_id" in data:
        u.grade_id = data["grade_id"] or None
    db.session.commit()
    return jsonify({"ok": True, "data": u.to_dict()})


@app.route("/api/users/bulk", methods=["POST"])
@login_required
def api_users_bulk():
    """선택한 여러 사용자에 대해 등급 일괄 변경 / 활성/비활성 일괄 처리"""
    if not is_admin():
        return jsonify({"ok": False, "msg": "권한이 없습니다."}), 403
    data = json_body()
    user_ids = data.get("user_ids") or []
    action = data.get("action")
    if not user_ids or not isinstance(user_ids, list):
        return jsonify({"ok": False, "msg": "대상 사용자를 선택해주세요."}), 400
    users = User.query.filter(User.id.in_(user_ids)).all()
    count = 0
    for u in users:
        if action == "set_grade":
            u.grade_id = data.get("grade_id") or None
            count += 1
        elif action == "activate":
            u.is_active_user = True
            count += 1
        elif action == "deactivate":
            u.is_active_user = False
            count += 1
        elif action == "delete":
            if u.id != current_user.id:
                db.session.delete(u)
                count += 1
    db.session.commit()
    log_admin_activity("사용자 일괄 처리", detail=f"{action} 처리 - {count}명")
    return jsonify({"ok": True, "count": count})


@app.route("/api/users/<int:uid>", methods=["DELETE"])
@login_required
def api_users_delete(uid):
    if not is_admin():
        return jsonify({"ok": False, "msg": "권한이 없습니다."}), 403
    if uid == current_user.id:
        return jsonify({"ok": False, "msg": "본인 계정은 삭제할 수 없습니다."}), 400
    u = User.query.get_or_404(uid)

    # Remove all related records first to avoid FK constraint violations.
    UserSubscription.query.filter_by(user_id=uid).delete()
    PlanChangeLog.query.filter_by(user_id=uid).delete()
    Crop.query.filter_by(user_id=uid).delete()
    Journal.query.filter_by(user_id=uid).delete()
    Task.query.filter_by(user_id=uid).delete()
    Inventory.query.filter_by(user_id=uid).delete()
    Shipment.query.filter_by(user_id=uid).delete()
    Post.query.filter_by(user_id=uid).delete()
    Diagnosis.query.filter_by(user_id=uid).delete()
    AdminActivityLog.query.filter_by(admin_id=uid).delete()
    AdminActivityLog.query.filter(AdminActivityLog.target_user_id == uid).update(
        {AdminActivityLog.target_user_id: None}
    )

    db.session.delete(u)
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"ok": False, "msg": f"삭제 중 오류가 발생했습니다: {e}"}), 500
    return jsonify({"ok": True})


@app.route("/api/users/<int:uid>/plan", methods=["PUT"])
@login_required
def api_users_change_plan(uid):
    if not is_admin():
        return jsonify({"ok": False, "msg": "권한이 없습니다."}), 403
    u = User.query.get_or_404(uid)
    data = json_body()
    plan_id = data.get("plan_id")
    plan = db.session.get(Plan, plan_id) if plan_id else None
    if not plan:
        return jsonify({"ok": False, "msg": "유효하지 않은 요금제입니다."}), 400
    billing_cycle = data.get("billing_cycle", "monthly")
    status = data.get("status", "active")
    expiry_date = data.get("expiry_date")
    is_waived = bool(data.get("is_waived", False))
    if not expiry_date and plan.code != "free":
        days = 365 if billing_cycle == "annual" else 30
        expiry_date = (date.today() + timedelta(days=days)).isoformat()

    prev = get_current_subscription(u.id)
    sub = UserSubscription(
        user_id=u.id, plan_id=plan.id, billing_cycle=billing_cycle,
        status=status, start_date=date.today().isoformat(), expiry_date=expiry_date,
        is_waived=is_waived,
    )
    db.session.add(sub)
    db.session.commit()

    log_admin_activity(
        "사용자 요금제 변경", target_user_id=u.id,
        detail=f"{u.name}님의 요금제를 '{plan.name}' ({billing_cycle})으로 변경"
    )
    log_plan_change(u.id, prev.get("plan_name"), plan.name, "admin_change",
                     detail=f"관리자에 의한 요금제 변경 ({billing_cycle})")
    return jsonify({"ok": True, "data": u.to_dict()})


@app.route("/api/users/<int:uid>/waive", methods=["POST"])
@login_required
def api_users_waive_plan(uid):
    """관리자가 사용자의 현재 요금제 이용료를 면제 처리"""
    if not is_admin():
        return jsonify({"ok": False, "msg": "권한이 없습니다."}), 403
    u = User.query.get_or_404(uid)
    data = json_body()
    waive = bool(data.get("waive", True))
    sub = (UserSubscription.query.filter_by(user_id=u.id)
           .order_by(UserSubscription.created_at.desc()).first())
    if not sub:
        return jsonify({"ok": False, "msg": "구독 정보가 없습니다."}), 400
    sub.is_waived = waive
    if waive:
        sub.status = "active"
    db.session.commit()
    plan = db.session.get(Plan, sub.plan_id)
    log_admin_activity(
        "요금제 면제" if waive else "요금제 면제 해제", target_user_id=u.id,
        detail=f"{u.name}님의 '{plan.name if plan else ''}' 요금제 이용료 {'면제' if waive else '면제 해제'}"
    )
    log_plan_change(u.id, plan.name if plan else None, plan.name if plan else None,
                     "waiver" if waive else "waiver_cancel",
                     detail="관리자 요금제 면제" if waive else "관리자 요금제 면제 해제")
    return jsonify({"ok": True, "data": u.to_dict()})


# ----------------------------------------------------------------------
# 요금제 관리 (Plans) API
# ----------------------------------------------------------------------
@app.route("/api/plans", methods=["GET"])
@login_required
def api_plans_list():
    q = Plan.query.order_by(Plan.display_order.asc(), Plan.id.asc())
    if not is_admin():
        q = q.filter_by(is_active=True)
    return jsonify({"ok": True, "data": [p.to_dict() for p in q.all()]})


@app.route("/api/plans", methods=["POST"])
@login_required
def api_plans_create():
    if not is_admin():
        return jsonify({"ok": False, "msg": "권한이 없습니다."}), 403
    data = json_body()
    code = (data.get("code") or "").strip()
    name = (data.get("name") or "").strip()
    if not code or not name:
        return jsonify({"ok": False, "msg": "요금제 코드와 이름은 필수입니다."}), 400
    if Plan.query.filter_by(code=code).first():
        return jsonify({"ok": False, "msg": "이미 존재하는 요금제 코드입니다."}), 400
    p = Plan(
        code=code, name=name,
        price_monthly=int(data.get("price_monthly") or 0),
        price_annual=int(data.get("price_annual") or 0),
        is_active=bool(data.get("is_active", True)),
        display_order=int(data.get("display_order") or 0),
    )
    p.set_features(data.get("features") or [])
    db.session.add(p)
    db.session.commit()
    log_admin_activity("요금제 생성", detail=f"'{p.name}' 요금제 생성")
    return jsonify({"ok": True, "data": p.to_dict()})


@app.route("/api/plans/<int:pid>", methods=["PUT"])
@login_required
def api_plans_update(pid):
    if not is_admin():
        return jsonify({"ok": False, "msg": "권한이 없습니다."}), 403
    p = Plan.query.get_or_404(pid)
    data = json_body()
    if "name" in data:
        p.name = data["name"]
    if "price_monthly" in data:
        p.price_monthly = int(data.get("price_monthly") or 0)
    if "price_annual" in data:
        p.price_annual = int(data.get("price_annual") or 0)
    if "features" in data:
        p.set_features(data.get("features") or [])
    if "is_active" in data:
        p.is_active = bool(data["is_active"])
    if "display_order" in data:
        p.display_order = int(data.get("display_order") or 0)
    db.session.commit()
    log_admin_activity("요금제 수정", detail=f"'{p.name}' 요금제 수정")
    return jsonify({"ok": True, "data": p.to_dict()})


@app.route("/api/plans/<int:pid>", methods=["DELETE"])
@login_required
def api_plans_delete(pid):
    if not is_admin():
        return jsonify({"ok": False, "msg": "권한이 없습니다."}), 403
    p = Plan.query.get_or_404(pid)
    if p.code == "free":
        return jsonify({"ok": False, "msg": "무료 요금제는 삭제할 수 없습니다."}), 400
    name = p.name
    UserSubscription.query.filter_by(plan_id=p.id).delete()
    db.session.delete(p)
    db.session.commit()
    log_admin_activity("요금제 삭제", detail=f"'{name}' 요금제 삭제")
    return jsonify({"ok": True})


# ----------------------------------------------------------------------
# 구독 (Subscriptions) API - 일반 사용자용
# ----------------------------------------------------------------------
@app.route("/api/subscriptions/me", methods=["GET"])
@login_required
def api_subscriptions_me():
    sub = get_current_subscription(current_user.id)
    return jsonify({"ok": True, "data": sub})


@app.route("/api/promo-codes/validate", methods=["POST"])
@login_required
def api_promo_validate():
    data = json_body()
    code = (data.get("code") or "").strip().upper()
    promo = PromoCode.query.filter(db.func.upper(PromoCode.code) == code).first()
    if not promo or not promo.is_valid():
        return jsonify({"ok": False, "msg": "유효하지 않거나 만료된 프로모션 코드입니다."}), 400
    return jsonify({"ok": True, "data": promo.to_dict()})


@app.route("/api/subscriptions/upgrade", methods=["POST"])
@login_required
def api_subscriptions_upgrade():
    data = json_body()
    plan_id = data.get("plan_id")
    plan = db.session.get(Plan, plan_id) if plan_id else None
    if not plan or not plan.is_active:
        return jsonify({"ok": False, "msg": "선택할 수 없는 요금제입니다."}), 400
    billing_cycle = data.get("billing_cycle", "monthly")
    if billing_cycle not in ("monthly", "annual"):
        billing_cycle = "monthly"

    promo_code_input = (data.get("promo_code") or "").strip()
    promo = None
    if promo_code_input:
        promo = PromoCode.query.filter(db.func.upper(PromoCode.code) == promo_code_input.upper()).first()
        if not promo or not promo.is_valid():
            return jsonify({"ok": False, "msg": "유효하지 않거나 만료된 프로모션 코드입니다."}), 400

    expiry_date = None
    if plan.code != "free":
        days = 365 if billing_cycle == "annual" else 30
        expiry_date = (date.today() + timedelta(days=days)).isoformat()

    prev = get_current_subscription(current_user.id)
    action = "upgrade"
    if prev.get("plan_id") and prev.get("plan_id") != plan.id:
        prev_plan = db.session.get(Plan, prev.get("plan_id"))
        if prev_plan and prev_plan.display_order > plan.display_order:
            action = "downgrade"

    sub = UserSubscription(
        user_id=current_user.id, plan_id=plan.id, billing_cycle=billing_cycle,
        status="active", start_date=date.today().isoformat(), expiry_date=expiry_date,
        promo_code=promo.code if promo else None,
    )
    db.session.add(sub)
    if promo:
        promo.used_count = (promo.used_count or 0) + 1
    db.session.commit()
    log_plan_change(current_user.id, prev.get("plan_name"), plan.name, action,
                     detail=f"{billing_cycle} 결제" + (f" / 프로모션 {promo.code} 적용" if promo else ""))
    return jsonify({"ok": True, "data": get_current_subscription(current_user.id)})


def _activate_subscription(user_id, plan, billing_cycle, promo=None):
    """Shared logic to activate a plan for a user (used by free-upgrade and paid checkout)."""
    expiry_date = None
    if plan.code != "free":
        days = 365 if billing_cycle == "annual" else 30
        expiry_date = (date.today() + timedelta(days=days)).isoformat()

    prev = get_current_subscription(user_id)
    action = "upgrade"
    if prev.get("plan_id") and prev.get("plan_id") != plan.id:
        prev_plan = db.session.get(Plan, prev.get("plan_id"))
        if prev_plan and prev_plan.display_order > plan.display_order:
            action = "downgrade"

    sub = UserSubscription(
        user_id=user_id, plan_id=plan.id, billing_cycle=billing_cycle,
        status="active", start_date=date.today().isoformat(), expiry_date=expiry_date,
        promo_code=promo.code if promo else None,
    )
    db.session.add(sub)
    if promo:
        promo.used_count = (promo.used_count or 0) + 1
    db.session.commit()
    log_plan_change(user_id, prev.get("plan_name"), plan.name, action,
                     detail=f"{billing_cycle} 결제" + (f" / 프로모션 {promo.code} 적용" if promo else ""))
    return get_current_subscription(user_id)


def _plan_price(plan, billing_cycle):
    return plan.price_annual if billing_cycle == "annual" else plan.price_monthly


TOSS_SECRET_KEY = os.environ.get("TOSS_SECRET_KEY", "")


@app.route("/api/payments/prepare", methods=["POST"])
@login_required
def api_payments_prepare():
    data = json_body()
    plan_id = data.get("plan_id")
    plan = db.session.get(Plan, plan_id) if plan_id else None
    if not plan or not plan.is_active:
        return jsonify({"ok": False, "msg": "선택할 수 없는 요금제입니다."}), 400
    billing_cycle = data.get("billing_cycle", "monthly")
    if billing_cycle not in ("monthly", "annual"):
        billing_cycle = "monthly"

    promo_code_input = (data.get("promo_code") or "").strip()
    promo = None
    if promo_code_input:
        promo = PromoCode.query.filter(db.func.upper(PromoCode.code) == promo_code_input.upper()).first()
        if not promo or not promo.is_valid():
            return jsonify({"ok": False, "msg": "유효하지 않거나 만료된 프로모션 코드입니다."}), 400

    base_amount = _plan_price(plan, billing_cycle)
    amount = base_amount
    if promo and promo.discount_percent:
        amount = round(base_amount * (1 - promo.discount_percent / 100))

    if amount <= 0:
        # Free plan or 100% discount: activate immediately, no payment needed.
        sub = _activate_subscription(current_user.id, plan, billing_cycle, promo)
        return jsonify({"ok": True, "data": {"free": True, "subscription": sub}})

    order_id = f"order_{uuid.uuid4().hex}"
    payment = Payment(
        user_id=current_user.id, plan_id=plan.id, order_id=order_id,
        order_name=f"{plan.name} 요금제 ({'연간' if billing_cycle == 'annual' else '월간'})",
        amount=amount, billing_cycle=billing_cycle,
        promo_code=promo.code if promo else None, status="pending",
    )
    db.session.add(payment)
    db.session.commit()
    return jsonify({"ok": True, "data": {
        "free": False, "order_id": order_id, "order_name": payment.order_name,
        "amount": amount, "customer_name": current_user.name, "customer_email": current_user.email,
    }})


@app.route("/api/payments/toss/confirm", methods=["POST"])
@login_required
def api_payments_toss_confirm():
    data = json_body()
    payment_key = data.get("paymentKey")
    order_id = data.get("orderId")
    amount = data.get("amount")
    if not payment_key or not order_id or amount is None:
        return jsonify({"ok": False, "msg": "잘못된 요청입니다."}), 400

    payment = Payment.query.filter_by(order_id=order_id, user_id=current_user.id).first()
    if not payment:
        return jsonify({"ok": False, "msg": "결제 정보를 찾을 수 없습니다."}), 404
    if payment.status == "approved":
        return jsonify({"ok": True, "data": get_current_subscription(current_user.id)})
    if int(amount) != int(payment.amount):
        return jsonify({"ok": False, "msg": "결제 금액이 일치하지 않습니다."}), 400
    if not TOSS_SECRET_KEY:
        return jsonify({"ok": False, "msg": "결제 서버 설정(TOSS_SECRET_KEY)이 완료되지 않았습니다."}), 500

    try:
        resp = requests.post(
            "https://api.tosspayments.com/v1/payments/confirm",
            json={"paymentKey": payment_key, "orderId": order_id, "amount": int(amount)},
            auth=(TOSS_SECRET_KEY, ""),
            timeout=15,
        )
    except requests.RequestException as e:
        return jsonify({"ok": False, "msg": f"결제 승인 요청 실패: {e}"}), 502

    result = resp.json() if resp.content else {}
    if resp.status_code != 200:
        payment.status = "failed"
        db.session.commit()
        return jsonify({"ok": False, "msg": result.get("message", "결제 승인에 실패했습니다.")}), 400

    plan = db.session.get(Plan, payment.plan_id)
    promo = None
    if payment.promo_code:
        promo = PromoCode.query.filter(db.func.upper(PromoCode.code) == payment.promo_code.upper()).first()

    payment.status = "approved"
    payment.payment_key = payment_key
    payment.method = result.get("method")
    payment.approved_at = datetime.utcnow()
    db.session.commit()

    sub = _activate_subscription(current_user.id, plan, payment.billing_cycle, promo)
    return jsonify({"ok": True, "data": sub})


# ----------------------------------------------------------------------
# 관리자 활동 로그 (Admin Activity Logs) API
# ----------------------------------------------------------------------
@app.route("/api/admin/activity-logs", methods=["GET"])
@login_required
def api_admin_activity_logs():
    if not is_admin():
        return jsonify({"ok": False, "msg": "권한이 없습니다."}), 403
    logs = AdminActivityLog.query.order_by(AdminActivityLog.created_at.desc()).limit(100).all()
    return jsonify({"ok": True, "data": [l.to_dict() for l in logs]})


@app.route("/api/admin/plan-change-logs", methods=["GET"])
@login_required
def api_admin_plan_change_logs():
    if not is_admin():
        return jsonify({"ok": False, "msg": "권한이 없습니다."}), 403
    logs = PlanChangeLog.query.order_by(PlanChangeLog.created_at.desc()).limit(100).all()
    return jsonify({"ok": True, "data": [l.to_dict() for l in logs]})


@app.route("/api/admin/stats", methods=["GET"])
@login_required
def api_admin_stats():
    if not is_admin():
        return jsonify({"ok": False, "msg": "권한이 없습니다."}), 403
    total_users = User.query.count()
    farmers = User.query.filter_by(role="farmer").count()
    admins = User.query.filter_by(role="admin").count()
    active_users = User.query.filter_by(is_active_user=True).count()
    total_posts = Post.query.count()
    total_diagnoses = Diagnosis.query.count()
    active_subs = UserSubscription.query.filter_by(status="active").count()
    waived_subs = UserSubscription.query.filter_by(is_waived=True).count()
    plan_counts = {}
    for plan in Plan.query.all():
        cnt = UserSubscription.query.filter_by(plan_id=plan.id, status="active").count()
        plan_counts[plan.name] = cnt
    grade_counts = {}
    for grade in Grade.query.all():
        cnt = User.query.filter_by(grade_id=grade.id).count()
        grade_counts[grade.name] = cnt
    return jsonify({"ok": True, "data": {
        "total_users": total_users, "farmers": farmers, "admins": admins,
        "active_users": active_users, "total_posts": total_posts,
        "total_diagnoses": total_diagnoses, "active_subscriptions": active_subs,
        "waived_subscriptions": waived_subs, "plan_counts": plan_counts,
        "grade_counts": grade_counts,
    }})


# ----------------------------------------------------------------------
# 등급 관리 (Grades) API
# ----------------------------------------------------------------------
@app.route("/api/grades", methods=["GET"])
@login_required
def api_grades_list():
    grades = Grade.query.order_by(Grade.display_order.asc(), Grade.id.asc()).all()
    return jsonify({"ok": True, "data": [g.to_dict() for g in grades]})


@app.route("/api/grades", methods=["POST"])
@login_required
def api_grades_create():
    if not is_admin():
        return jsonify({"ok": False, "msg": "권한이 없습니다."}), 403
    data = json_body()
    code = (data.get("code") or "").strip()
    name = (data.get("name") or "").strip()
    if not code or not name:
        return jsonify({"ok": False, "msg": "등급 코드와 이름은 필수입니다."}), 400
    if Grade.query.filter_by(code=code).first():
        return jsonify({"ok": False, "msg": "이미 존재하는 등급 코드입니다."}), 400
    g = Grade(
        code=code, name=name,
        discount_percent=int(data.get("discount_percent") or 0),
        min_spend=int(data.get("min_spend") or 0),
        color=data.get("color") or "#6b746b",
        display_order=int(data.get("display_order") or 0),
        description=data.get("description"),
    )
    db.session.add(g)
    db.session.commit()
    log_admin_activity("등급 생성", detail=f"'{g.name}' 등급 생성")
    return jsonify({"ok": True, "data": g.to_dict()})


@app.route("/api/grades/<int:gid>", methods=["PUT"])
@login_required
def api_grades_update(gid):
    if not is_admin():
        return jsonify({"ok": False, "msg": "권한이 없습니다."}), 403
    g = Grade.query.get_or_404(gid)
    data = json_body()
    if "name" in data:
        g.name = data["name"]
    if "discount_percent" in data:
        g.discount_percent = int(data.get("discount_percent") or 0)
    if "min_spend" in data:
        g.min_spend = int(data.get("min_spend") or 0)
    if "color" in data:
        g.color = data["color"]
    if "display_order" in data:
        g.display_order = int(data.get("display_order") or 0)
    if "description" in data:
        g.description = data["description"]
    db.session.commit()
    log_admin_activity("등급 수정", detail=f"'{g.name}' 등급 수정")
    return jsonify({"ok": True, "data": g.to_dict()})


@app.route("/api/grades/<int:gid>", methods=["DELETE"])
@login_required
def api_grades_delete(gid):
    if not is_admin():
        return jsonify({"ok": False, "msg": "권한이 없습니다."}), 403
    g = Grade.query.get_or_404(gid)
    User.query.filter_by(grade_id=g.id).update({"grade_id": None})
    name = g.name
    db.session.delete(g)
    db.session.commit()
    log_admin_activity("등급 삭제", detail=f"'{name}' 등급 삭제")
    return jsonify({"ok": True})


# ----------------------------------------------------------------------
# 프로모션 코드 관리 (Promo Codes) API
# ----------------------------------------------------------------------
@app.route("/api/admin/promo-codes", methods=["GET"])
@login_required
def api_promo_codes_list():
    if not is_admin():
        return jsonify({"ok": False, "msg": "권한이 없습니다."}), 403
    codes = PromoCode.query.order_by(PromoCode.created_at.desc()).all()
    return jsonify({"ok": True, "data": [c.to_dict() for c in codes]})


@app.route("/api/admin/promo-codes", methods=["POST"])
@login_required
def api_promo_codes_create():
    if not is_admin():
        return jsonify({"ok": False, "msg": "권한이 없습니다."}), 403
    data = json_body()
    code = (data.get("code") or "").strip().upper()
    if not code:
        return jsonify({"ok": False, "msg": "코드는 필수입니다."}), 400
    if PromoCode.query.filter_by(code=code).first():
        return jsonify({"ok": False, "msg": "이미 존재하는 코드입니다."}), 400
    p = PromoCode(
        code=code, discount_percent=int(data.get("discount_percent") or 0),
        description=data.get("description"), is_active=bool(data.get("is_active", True)),
        max_uses=int(data.get("max_uses") or 0), expiry_date=data.get("expiry_date"),
    )
    db.session.add(p)
    db.session.commit()
    log_admin_activity("프로모션 코드 생성", detail=f"'{p.code}' 코드 생성")
    return jsonify({"ok": True, "data": p.to_dict()})


@app.route("/api/admin/promo-codes/<int:pid>", methods=["PUT"])
@login_required
def api_promo_codes_update(pid):
    if not is_admin():
        return jsonify({"ok": False, "msg": "권한이 없습니다."}), 403
    p = PromoCode.query.get_or_404(pid)
    data = json_body()
    if "discount_percent" in data:
        p.discount_percent = int(data.get("discount_percent") or 0)
    if "description" in data:
        p.description = data["description"]
    if "is_active" in data:
        p.is_active = bool(data["is_active"])
    if "max_uses" in data:
        p.max_uses = int(data.get("max_uses") or 0)
    if "expiry_date" in data:
        p.expiry_date = data["expiry_date"]
    db.session.commit()
    log_admin_activity("프로모션 코드 수정", detail=f"'{p.code}' 코드 수정")
    return jsonify({"ok": True, "data": p.to_dict()})


@app.route("/api/admin/promo-codes/<int:pid>", methods=["DELETE"])
@login_required
def api_promo_codes_delete(pid):
    if not is_admin():
        return jsonify({"ok": False, "msg": "권한이 없습니다."}), 403
    p = PromoCode.query.get_or_404(pid)
    code = p.code
    db.session.delete(p)
    db.session.commit()
    log_admin_activity("프로모션 코드 삭제", detail=f"'{code}' 코드 삭제")
    return jsonify({"ok": True})


# ----------------------------------------------------------------------
# 농업 링크 모음 (Links) API
# ----------------------------------------------------------------------
@app.route("/api/links", methods=["GET"])
@login_required
def api_links_list():
    links = Link.query.order_by(Link.category.asc(), Link.display_order.asc(), Link.id.asc()).all()
    return jsonify({"ok": True, "data": [l.to_dict() for l in links]})


@app.route("/api/links", methods=["POST"])
@login_required
def api_links_create():
    if not is_admin():
        return jsonify({"ok": False, "msg": "권한이 없습니다."}), 403
    data = json_body()
    title = (data.get("title") or "").strip()
    url = (data.get("url") or "").strip()
    if not title or not url:
        return jsonify({"ok": False, "msg": "제목과 URL은 필수입니다."}), 400
    l = Link(
        title=title, url=url, category=data.get("category") or "공공기관",
        description=data.get("description"),
        display_order=int(data.get("display_order") or 0),
    )
    db.session.add(l)
    db.session.commit()
    log_admin_activity("링크 추가", detail=f"'{l.title}' 링크 추가")
    return jsonify({"ok": True, "data": l.to_dict()})


@app.route("/api/links/<int:lid>", methods=["PUT"])
@login_required
def api_links_update(lid):
    if not is_admin():
        return jsonify({"ok": False, "msg": "권한이 없습니다."}), 403
    l = Link.query.get_or_404(lid)
    data = json_body()
    if "title" in data:
        l.title = data["title"]
    if "url" in data:
        l.url = data["url"]
    if "category" in data:
        l.category = data["category"]
    if "description" in data:
        l.description = data["description"]
    if "display_order" in data:
        l.display_order = int(data.get("display_order") or 0)
    db.session.commit()
    log_admin_activity("링크 수정", detail=f"'{l.title}' 링크 수정")
    return jsonify({"ok": True, "data": l.to_dict()})


@app.route("/api/links/<int:lid>", methods=["DELETE"])
@login_required
def api_links_delete(lid):
    if not is_admin():
        return jsonify({"ok": False, "msg": "권한이 없습니다."}), 403
    l = Link.query.get_or_404(lid)
    title = l.title
    db.session.delete(l)
    db.session.commit()
    log_admin_activity("링크 삭제", detail=f"'{title}' 링크 삭제")
    return jsonify({"ok": True})


# ----------------------------------------------------------------------
# 공통 CRUD 헬퍼
# ----------------------------------------------------------------------
def owned_query(model):
    """관리자는 전체, 일반 농민은 본인 데이터만 조회"""
    q = model.query
    if not is_admin():
        q = q.filter_by(user_id=current_user.id)
    return q


def owned_or_shared_query(model):
    """본인 데이터 전체 + 다른 회원이 '공개'로 등록한 데이터. 관리자는 전체 조회."""
    if is_admin():
        return model.query
    return model.query.filter(
        db.or_(model.user_id == current_user.id, model.is_public.is_(True))
    )


def parse_is_public(data):
    val = data.get("is_public")
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in ("true", "1", "on", "yes", "공개")


# ----------------------------------------------------------------------
# 작물 관리 (Crops)
# ----------------------------------------------------------------------
@app.route("/api/crops", methods=["GET"])
@login_required
def api_crops_list():
    items = owned_or_shared_query(Crop).order_by(Crop.created_at.desc()).all()
    return jsonify({"ok": True, "data": [c.to_dict() for c in items]})


@app.route("/api/crops", methods=["POST"])
@login_required
def api_crops_create():
    data = request.form if request.form else json_body()
    image_path = save_upload(request.files.get("image")) if request.files else None
    c = Crop(
        user_id=current_user.id,
        name=data.get("name"),
        variety=data.get("variety"),
        field_location=data.get("field_location"),
        area=float(data.get("area") or 0) or None,
        planting_date=data.get("planting_date"),
        expected_harvest_date=data.get("expected_harvest_date"),
        status=data.get("status", "재배중"),
        memo=data.get("memo"),
        image=image_path,
        is_public=parse_is_public(data) or False,
    )
    db.session.add(c)
    db.session.commit()
    return jsonify({"ok": True, "data": c.to_dict()})


@app.route("/api/crops/<int:cid>", methods=["PUT"])
@login_required
def api_crops_update(cid):
    c = Crop.query.get_or_404(cid)
    if not is_admin() and c.user_id != current_user.id:
        return jsonify({"ok": False, "msg": "권한이 없습니다."}), 403
    data = request.form if request.form else json_body()
    if request.files and request.files.get("image"):
        img = save_upload(request.files.get("image"))
        if img:
            c.image = img
    for field in ["name", "variety", "field_location", "planting_date",
                  "expected_harvest_date", "status", "memo"]:
        if field in data:
            setattr(c, field, data.get(field))
    if "area" in data and data.get("area"):
        c.area = float(data.get("area"))
    pub = parse_is_public(data)
    if pub is not None:
        c.is_public = pub
    db.session.commit()
    return jsonify({"ok": True, "data": c.to_dict()})


@app.route("/api/crops/<int:cid>", methods=["DELETE"])
@login_required
def api_crops_delete(cid):
    c = Crop.query.get_or_404(cid)
    if not is_admin() and c.user_id != current_user.id:
        return jsonify({"ok": False, "msg": "권한이 없습니다."}), 403
    db.session.delete(c)
    db.session.commit()
    return jsonify({"ok": True})


# ----------------------------------------------------------------------
# 영농 일지 (Journals)
# ----------------------------------------------------------------------
@app.route("/api/journals", methods=["GET"])
@login_required
def api_journals_list():
    items = owned_or_shared_query(Journal).order_by(Journal.date.desc()).all()
    return jsonify({"ok": True, "data": [j.to_dict() for j in items]})


@app.route("/api/journals", methods=["POST"])
@login_required
def api_journals_create():
    data = request.form if request.form else json_body()
    image_path = save_upload(request.files.get("image")) if request.files else None
    j = Journal(
        user_id=current_user.id,
        crop_id=int(data.get("crop_id")) if data.get("crop_id") else None,
        date=data.get("date") or date.today().isoformat(),
        work_type=data.get("work_type"),
        weather=data.get("weather"),
        content=data.get("content"),
        image=image_path,
        is_public=parse_is_public(data) or False,
    )
    db.session.add(j)
    db.session.commit()
    return jsonify({"ok": True, "data": j.to_dict()})


@app.route("/api/journals/<int:jid>", methods=["PUT"])
@login_required
def api_journals_update(jid):
    j = Journal.query.get_or_404(jid)
    if not is_admin() and j.user_id != current_user.id:
        return jsonify({"ok": False, "msg": "권한이 없습니다."}), 403
    data = request.form if request.form else json_body()
    if request.files and request.files.get("image"):
        img = save_upload(request.files.get("image"))
        if img:
            j.image = img
    for field in ["date", "work_type", "weather", "content"]:
        if field in data:
            setattr(j, field, data.get(field))
    if "crop_id" in data:
        j.crop_id = int(data.get("crop_id")) if data.get("crop_id") else None
    pub = parse_is_public(data)
    if pub is not None:
        j.is_public = pub
    db.session.commit()
    return jsonify({"ok": True, "data": j.to_dict()})


@app.route("/api/journals/<int:jid>", methods=["DELETE"])
@login_required
def api_journals_delete(jid):
    j = Journal.query.get_or_404(jid)
    if not is_admin() and j.user_id != current_user.id:
        return jsonify({"ok": False, "msg": "권한이 없습니다."}), 403
    db.session.delete(j)
    db.session.commit()
    return jsonify({"ok": True})


# ----------------------------------------------------------------------
# 작업 일정 (Tasks)
# ----------------------------------------------------------------------
@app.route("/api/tasks", methods=["GET"])
@login_required
def api_tasks_list():
    items = owned_or_shared_query(Task).order_by(Task.due_date.asc()).all()
    return jsonify({"ok": True, "data": [t.to_dict() for t in items]})


@app.route("/api/tasks", methods=["POST"])
@login_required
def api_tasks_create():
    data = json_body()
    t = Task(
        user_id=current_user.id,
        crop_id=int(data.get("crop_id")) if data.get("crop_id") else None,
        title=data.get("title"),
        memo=data.get("memo"),
        due_date=data.get("due_date"),
        priority=data.get("priority", "보통"),
        status=data.get("status", "예정"),
        is_public=parse_is_public(data) or False,
    )
    db.session.add(t)
    db.session.commit()
    return jsonify({"ok": True, "data": t.to_dict()})


@app.route("/api/tasks/<int:tid>", methods=["PUT"])
@login_required
def api_tasks_update(tid):
    t = Task.query.get_or_404(tid)
    if not is_admin() and t.user_id != current_user.id:
        return jsonify({"ok": False, "msg": "권한이 없습니다."}), 403
    data = json_body()
    for field in ["title", "memo", "due_date", "priority", "status"]:
        if field in data:
            setattr(t, field, data.get(field))
    if "crop_id" in data:
        t.crop_id = int(data.get("crop_id")) if data.get("crop_id") else None
    pub = parse_is_public(data)
    if pub is not None:
        t.is_public = pub
    db.session.commit()
    return jsonify({"ok": True, "data": t.to_dict()})


@app.route("/api/tasks/<int:tid>", methods=["DELETE"])
@login_required
def api_tasks_delete(tid):
    t = Task.query.get_or_404(tid)
    if not is_admin() and t.user_id != current_user.id:
        return jsonify({"ok": False, "msg": "권한이 없습니다."}), 403
    db.session.delete(t)
    db.session.commit()
    return jsonify({"ok": True})


# ----------------------------------------------------------------------
# 재고 관리 (Inventory)
# ----------------------------------------------------------------------
@app.route("/api/inventory", methods=["GET"])
@login_required
def api_inventory_list():
    items = owned_query(Inventory).order_by(Inventory.created_at.desc()).all()
    return jsonify({"ok": True, "data": [i.to_dict() for i in items]})


@app.route("/api/inventory", methods=["POST"])
@login_required
def api_inventory_create():
    data = json_body()
    i = Inventory(
        user_id=current_user.id,
        name=data.get("name"),
        category=data.get("category"),
        quantity=float(data.get("quantity") or 0),
        unit=data.get("unit"),
        location=data.get("location"),
        expiry_date=data.get("expiry_date"),
        memo=data.get("memo"),
    )
    db.session.add(i)
    db.session.commit()
    return jsonify({"ok": True, "data": i.to_dict()})


@app.route("/api/inventory/<int:iid>", methods=["PUT"])
@login_required
def api_inventory_update(iid):
    i = Inventory.query.get_or_404(iid)
    if not is_admin() and i.user_id != current_user.id:
        return jsonify({"ok": False, "msg": "권한이 없습니다."}), 403
    data = json_body()
    for field in ["name", "category", "unit", "location", "expiry_date", "memo"]:
        if field in data:
            setattr(i, field, data.get(field))
    if "quantity" in data:
        i.quantity = float(data.get("quantity") or 0)
    db.session.commit()
    return jsonify({"ok": True, "data": i.to_dict()})


@app.route("/api/inventory/<int:iid>", methods=["DELETE"])
@login_required
def api_inventory_delete(iid):
    i = Inventory.query.get_or_404(iid)
    if not is_admin() and i.user_id != current_user.id:
        return jsonify({"ok": False, "msg": "권한이 없습니다."}), 403
    db.session.delete(i)
    db.session.commit()
    return jsonify({"ok": True})


# ----------------------------------------------------------------------
# 출하 관리 (Shipments)
# ----------------------------------------------------------------------
@app.route("/api/shipments", methods=["GET"])
@login_required
def api_shipments_list():
    items = owned_query(Shipment).order_by(Shipment.shipment_date.desc()).all()
    return jsonify({"ok": True, "data": [s.to_dict() for s in items]})


@app.route("/api/shipments", methods=["POST"])
@login_required
def api_shipments_create():
    data = json_body()
    s = Shipment(
        user_id=current_user.id,
        crop_id=int(data.get("crop_id")) if data.get("crop_id") else None,
        buyer=data.get("buyer"),
        quantity=float(data.get("quantity") or 0),
        unit=data.get("unit"),
        unit_price=float(data.get("unit_price") or 0),
        shipment_date=data.get("shipment_date"),
        status=data.get("status", "예정"),
        memo=data.get("memo"),
    )
    db.session.add(s)
    db.session.commit()
    return jsonify({"ok": True, "data": s.to_dict()})


@app.route("/api/shipments/<int:sid>", methods=["PUT"])
@login_required
def api_shipments_update(sid):
    s = Shipment.query.get_or_404(sid)
    if not is_admin() and s.user_id != current_user.id:
        return jsonify({"ok": False, "msg": "권한이 없습니다."}), 403
    data = json_body()
    for field in ["buyer", "unit", "shipment_date", "status", "memo"]:
        if field in data:
            setattr(s, field, data.get(field))
    if "quantity" in data:
        s.quantity = float(data.get("quantity") or 0)
    if "unit_price" in data:
        s.unit_price = float(data.get("unit_price") or 0)
    if "crop_id" in data:
        s.crop_id = int(data.get("crop_id")) if data.get("crop_id") else None
    db.session.commit()
    return jsonify({"ok": True, "data": s.to_dict()})


@app.route("/api/shipments/<int:sid>", methods=["DELETE"])
@login_required
def api_shipments_delete(sid):
    s = Shipment.query.get_or_404(sid)
    if not is_admin() and s.user_id != current_user.id:
        return jsonify({"ok": False, "msg": "권한이 없습니다."}), 403
    db.session.delete(s)
    db.session.commit()
    return jsonify({"ok": True})


# ----------------------------------------------------------------------
# 커뮤니티 (Posts)
# ----------------------------------------------------------------------
@app.route("/api/posts", methods=["GET"])
@login_required
def api_posts_list():
    category = request.args.get("category", "").strip()
    search = request.args.get("q", "").strip()
    page = max(int(request.args.get("page", 1) or 1), 1)
    per_page = min(max(int(request.args.get("per_page", 10) or 10), 1), 100)

    q = Post.query
    if category and category != "전체":
        q = q.filter_by(category=category)
    if search:
        like = f"%{search}%"
        q = q.filter(db.or_(Post.title.like(like), Post.content.like(like)))

    pinned = q.filter_by(is_pinned=True).order_by(Post.created_at.desc()).all()
    normal_q = q.filter_by(is_pinned=False).order_by(Post.created_at.desc())
    total = normal_q.count()
    normal = normal_q.offset((page - 1) * per_page).limit(per_page).all()

    result_items = pinned + normal if page == 1 else normal
    return jsonify({
        "ok": True,
        "data": [p.to_dict() for p in result_items],
        "pinned": [p.to_dict() for p in pinned] if page == 1 else [],
        "page": page, "per_page": per_page, "total": total,
        "total_pages": max((total + per_page - 1) // per_page, 1),
    })


@app.route("/api/posts/<int:pid>", methods=["GET"])
@login_required
def api_posts_detail(pid):
    p = Post.query.get_or_404(pid)
    p.views = (p.views or 0) + 1
    db.session.commit()
    return jsonify({"ok": True, "data": p.to_dict()})


@app.route("/api/posts", methods=["POST"])
@login_required
def api_posts_create():
    data = request.form if request.form else json_body()
    image_path = save_upload(request.files.get("image")) if request.files else None
    is_pinned = bool(data.get("is_pinned")) if is_admin() else False
    p = Post(
        user_id=current_user.id,
        category=data.get("category", "자유"),
        title=data.get("title"),
        content=data.get("content"),
        image=image_path,
        is_pinned=is_pinned,
    )
    db.session.add(p)
    db.session.commit()
    return jsonify({"ok": True, "data": p.to_dict()})


@app.route("/api/posts/<int:pid>", methods=["PUT"])
@login_required
def api_posts_update(pid):
    p = Post.query.get_or_404(pid)
    if not is_admin() and p.user_id != current_user.id:
        return jsonify({"ok": False, "msg": "권한이 없습니다."}), 403
    data = request.form if request.form else json_body()
    for field in ["category", "title", "content"]:
        if field in data:
            setattr(p, field, data.get(field))
    if "is_pinned" in data and is_admin():
        val = data.get("is_pinned")
        p.is_pinned = val if isinstance(val, bool) else str(val).lower() in ("true", "1", "on")
    db.session.commit()
    return jsonify({"ok": True, "data": p.to_dict()})


@app.route("/api/posts/<int:pid>", methods=["DELETE"])
@login_required
def api_posts_delete(pid):
    p = Post.query.get_or_404(pid)
    if not is_admin() and p.user_id != current_user.id:
        return jsonify({"ok": False, "msg": "권한이 없습니다."}), 403
    db.session.delete(p)
    db.session.commit()
    return jsonify({"ok": True})


# ----------------------------------------------------------------------
# AI 작물 진단 (Diagnoses) - Gemini Vision 연동
# ----------------------------------------------------------------------
DISEASE_DB = [
    {"name": "정상 (건강한 잎)", "severity": "정상",
     "advice": "특별한 이상 징후가 없습니다. 현재의 관리 방식을 유지하세요."},
    {"name": "잎마름병", "severity": "경고",
     "advice": "감염된 잎을 즉시 제거하고 통풍을 개선하세요. 적용 가능한 살균제를 살포하세요."},
    {"name": "흰가루병", "severity": "경고",
     "advice": "습도를 낮추고 밀식을 피하세요. 유황 성분 살균제 처리를 권장합니다."},
    {"name": "탄저병", "severity": "위험",
     "advice": "이병 부위를 즉시 제거 및 폐기하고, 등록된 전용 살균제를 즉시 살포하세요."},
    {"name": "노균병", "severity": "위험",
     "advice": "배수를 개선하고 감염 잎을 제거하세요. 예방적 살균제 살포가 필요합니다."},
    {"name": "질소 결핍 의심", "severity": "주의",
     "advice": "요소 비료 등 질소질 비료 추가 시비를 검토하세요."},
    {"name": "응애류 피해 의심", "severity": "주의",
     "advice": "잎 뒷면을 확인하고 적용 살충제(응애 전용)를 살포하세요."},
]


def _fallback_diagnosis():
    result = random.choice(DISEASE_DB)
    return {
        "disease_name": result["name"],
        "confidence": round(random.uniform(72.0, 98.5), 1),
        "severity": result["severity"],
        "advice": result["advice"],
        "ai": False,
    }


def _parse_gemini_response(text):
    """Gemini 응답에서 JSON을 추출하거나 자유 텍스트를 파싱한다."""
    import re
    text = text.strip()
    json_match = re.search(r"\{.*\}", text, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group(0))
            return {
                "disease_name": data.get("disease_name", data.get("병해충명", "진단 결과 없음")),
                "confidence": float(data.get("confidence", data.get("확신도", 85))),
                "severity": data.get("severity", data.get("심각도", "주의")),
                "advice": data.get("advice", data.get("조치법", text)),
                "ai": True,
            }
        except Exception:
            pass
    lines = [ln.strip("- * \n\r") for ln in text.splitlines() if ln.strip()]
    disease = "진단 결과 없음"
    severity = "주의"
    advice = text
    for ln in lines:
        if "병해충" in ln or "질병" in ln:
            disease = ln.split(":", 1)[-1].strip() or ln
        elif "심각도" in ln or "위험" in ln or "경고" in ln or "주의" in ln or "정상" in ln:
            for s in ["위험", "경고", "주의", "정상"]:
                if s in ln:
                    severity = s
                    break
        elif "조치" in ln or "관리" in ln or "방법" in ln:
            advice = ln.split(":", 1)[-1].strip() or ln
    return {"disease_name": disease, "confidence": 85.0, "severity": severity, "advice": advice, "ai": True}


def analyze_plant_image(image_full_path, crop_name="미지정"):
    """Gemini Vision API로 식물 이미지를 분석한다. 실패 시 fallback 반환."""
    if not genai or not GEMINI_API_KEY:
        return _fallback_diagnosis()

    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        with open(image_full_path, "rb") as f:
            image_data = f.read()
        ext = image_full_path.rsplit(".", 1)[-1].lower()
        mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                "gif": "image/gif", "webp": "image/webp"}.get(ext, "image/jpeg")

        prompt = (
            f"이 사진은 농작물 '{crop_name}'의 병해충 진단용 사진입니다. "
            "사진을 분석하고 아래 JSON 형식으로만 답변해주세요. "
            "disease_name은 병해충/질병 이름(한국어), confidence는 0~100 사이 확신도 숫자, "
            "severity는 '정상', '주의', '경고', '위험' 중 하나, advice는 100자 내외의 구체적 대처법(한국어)입니다.\n"
            "{\"disease_name\":\"...\",\"confidence\":85,\"severity\":\"...\",\"advice\":\"...\"}"
        )

        response = model.generate_content(
            [{"mime_type": mime, "data": image_data}, prompt],
            generation_config={"temperature": 0.2, "max_output_tokens": 512}
        )
        text = response.text or ""
        result = _parse_gemini_response(text)
        return result
    except Exception as e:
        print(f"Gemini diagnosis error: {e}")
        return _fallback_diagnosis()


@app.route("/api/diagnoses", methods=["GET"])
@login_required
def api_diagnoses_list():
    items = owned_query(Diagnosis).order_by(Diagnosis.created_at.desc()).all()
    return jsonify({"ok": True, "data": [d.to_dict() for d in items]})


@app.route("/api/diagnoses", methods=["POST"])
@login_required
def api_diagnoses_create():
    data = request.form if request.form else json_body()
    image_path = save_upload(request.files.get("image")) if request.files else None
    if not image_path:
        return jsonify({"ok": False, "msg": "진단할 이미지를 업로드해주세요."}), 400

    crop_name = data.get("crop_name", "미지정")
    full_path = os.path.join(UPLOAD_FOLDER, os.path.basename(image_path))
    result = analyze_plant_image(full_path, crop_name)

    d = Diagnosis(
        user_id=current_user.id,
        crop_name=crop_name,
        image=image_path,
        disease_name=result["disease_name"],
        confidence=result["confidence"],
        severity=result["severity"],
        advice=result["advice"],
    )
    db.session.add(d)
    db.session.commit()
    return jsonify({"ok": True, "data": d.to_dict()})


@app.route("/api/diagnoses/<int:did>", methods=["DELETE"])
@login_required
def api_diagnoses_delete(did):
    d = Diagnosis.query.get_or_404(did)
    if not is_admin() and d.user_id != current_user.id:
        return jsonify({"ok": False, "msg": "권한이 없습니다."}), 403
    db.session.delete(d)
    db.session.commit()
    return jsonify({"ok": True})


# ----------------------------------------------------------------------
# 농업진흥청 새소식 (RDA Notices)
# ----------------------------------------------------------------------
RDA_NOTICE_URL = "https://www.rda.go.kr/board/board.do?mode=list&prgId=nei_ancmttEntry"
_rda_last_scraped_at = None


def scrape_rda_notices():
    """농촌진흥청 공지사항 게시판을 스크래핑하여 RdaNotice 테이블에 upsert 한다."""
    global _rda_last_scraped_at
    try:
        resp = requests.get(RDA_NOTICE_URL, timeout=10,
                             headers={"User-Agent": "Mozilla/5.0"})
        resp.encoding = resp.apparent_encoding
        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.select_one("table.tbl.data")
        if not table:
            return 0
        rows = table.select("tbody tr")
        added = 0
        for row in rows:
            a = row.select_one("td[aria-label='제목'] a")
            if not a:
                continue
            title = a.get_text(strip=True)
            href = a.get("href") or ""
            date_td = row.select_one("td[aria-label='작성일']")
            notice_date = date_td.get_text(strip=True) if date_td else date.today().isoformat()
            source_url = "https://www.rda.go.kr" + href if href.startswith("/") else href
            exists = RdaNotice.query.filter_by(title=title, notice_date=notice_date).first()
            if exists:
                continue
            n = RdaNotice(
                title=title,
                content=None,
                category="공지",
                notice_date=notice_date,
                source_url=source_url,
            )
            db.session.add(n)
            added += 1
        if added:
            db.session.commit()
        _rda_last_scraped_at = datetime.utcnow()
        return added
    except Exception as e:
        print(f"[RDA scrape error] {e}")
        return 0


@app.route("/api/rda", methods=["GET"])
@login_required
def api_rda_list():
    global _rda_last_scraped_at
    stale = (_rda_last_scraped_at is None or
             (datetime.utcnow() - _rda_last_scraped_at).total_seconds() > 6 * 3600)
    if stale:
        scrape_rda_notices()
    items = RdaNotice.query.order_by(RdaNotice.notice_date.desc()).all()
    return jsonify({"ok": True, "data": [n.to_dict() for n in items]})


@app.route("/api/rda/refresh", methods=["POST"])
@login_required
def api_rda_refresh():
    if not is_admin():
        return jsonify({"ok": False, "msg": "권한이 없습니다."}), 403
    added = scrape_rda_notices()
    items = RdaNotice.query.order_by(RdaNotice.notice_date.desc()).all()
    return jsonify({"ok": True, "added": added, "data": [n.to_dict() for n in items]})


@app.route("/api/rda", methods=["POST"])
@login_required
def api_rda_create():
    if not is_admin():
        return jsonify({"ok": False, "msg": "권한이 없습니다."}), 403
    data = json_body()
    n = RdaNotice(
        title=data.get("title"),
        content=data.get("content"),
        category=data.get("category", "공지"),
        notice_date=data.get("notice_date") or date.today().isoformat(),
        source_url=data.get("source_url"),
    )
    db.session.add(n)
    db.session.commit()
    return jsonify({"ok": True, "data": n.to_dict()})


@app.route("/api/rda/<int:nid>", methods=["DELETE"])
@login_required
def api_rda_delete(nid):
    if not is_admin():
        return jsonify({"ok": False, "msg": "권한이 없습니다."}), 403
    n = RdaNotice.query.get_or_404(nid)
    db.session.delete(n)
    db.session.commit()
    return jsonify({"ok": True})


# ----------------------------------------------------------------------
# 농산물 시세 (Market Prices) - KAMIS Open API 실시간 연동 (키 없으면 모의 데이터로 폴백)
# ----------------------------------------------------------------------
MARKET_ITEMS = [
    {"name": "배추", "unit": "포기", "base": 3200},
    {"name": "무", "unit": "개", "base": 1800},
    {"name": "양파", "unit": "kg", "base": 2100},
    {"name": "감자", "unit": "kg", "base": 2600},
    {"name": "고구마", "unit": "kg", "base": 3800},
    {"name": "쌀", "unit": "20kg", "base": 52000},
    {"name": "상추", "unit": "kg", "base": 4500},
    {"name": "토마토", "unit": "kg", "base": 5200},
    {"name": "오이", "unit": "kg", "base": 3600},
    {"name": "딸기", "unit": "kg", "base": 15000},
    {"name": "사과", "unit": "kg", "base": 6800},
    {"name": "고추(건)", "unit": "kg", "base": 22000},
]

KAMIS_CERT_KEY = os.environ.get("KAMIS_CERT_KEY", "")
KAMIS_CERT_ID = os.environ.get("KAMIS_CERT_ID", "")
KAMIS_URL = "http://www.kamis.or.kr/service/price/xml.do"

MARKET_MIN_DATE = date(2020, 1, 1)


def _mock_market_data(regday):
    random.seed(date.fromisoformat(regday).toordinal())
    data = []
    for item in MARKET_ITEMS:
        change_pct = round(random.uniform(-8.0, 8.0), 1)
        price = int(item["base"] * (1 + change_pct / 100))
        data.append({
            "name": item["name"], "unit": item["unit"],
            "price": price, "change_pct": change_pct,
            "trend": "up" if change_pct > 0 else ("down" if change_pct < 0 else "flat"),
            "source": "mock",
        })
    random.seed()
    return data


def fetch_kamis_prices(regday):
    """KAMIS Open API(dailyPriceByCategoryList)로 지정한 날짜(regday, YYYY-MM-DD)의
    식량작물/채소류/과일류 소매가격을 조회해 MARKET_ITEMS 이름과 매칭되는 실제 시세를 반환한다.
    실패 시 None."""
    if not KAMIS_CERT_KEY or not KAMIS_CERT_ID:
        return None
    wanted = {it["name"]: it for it in MARKET_ITEMS}
    found = {}
    try:
        for category_code in ("100", "200", "300", "400", "500"):  # 식량작물/채소류/특용작물/과일류/기타
            resp = requests.get(KAMIS_URL, params={
                "action": "dailyPriceByCategoryList",
                "p_cert_key": KAMIS_CERT_KEY,
                "p_cert_id": KAMIS_CERT_ID,
                "p_returntype": "json",
                "p_product_cls_code": "01",  # 소매
                "p_item_category_code": category_code,
                "p_regday": regday,
                "p_convert_kg_yn": "N",
            }, timeout=8)
            payload = resp.json()
            rows = payload.get("data", {}).get("item", []) if isinstance(payload.get("data"), dict) else []
            for row in rows:
                name = (row.get("item_name") or "").strip()
                if name not in wanted or name in found:
                    continue
                try:
                    today_price = int(str(row.get("dpr1", "0")).replace(",", "") or 0)
                    prev_price = int(str(row.get("dpr2", "0")).replace(",", "") or 0)
                except (ValueError, TypeError):
                    continue
                if today_price <= 0:
                    continue
                change_pct = round((today_price - prev_price) / prev_price * 100, 1) if prev_price > 0 else 0.0
                found[name] = {
                    "name": name, "unit": wanted[name]["unit"],
                    "price": today_price, "change_pct": change_pct,
                    "trend": "up" if change_pct > 0 else ("down" if change_pct < 0 else "flat"),
                    "source": "kamis",
                }
        if not found:
            return None
        # 매칭 안 된 품목은 기존 순서 유지를 위해 모의 데이터로 보충
        mock_by_name = {m["name"]: m for m in _mock_market_data(regday)}
        return [found.get(it["name"], mock_by_name[it["name"]]) for it in MARKET_ITEMS]
    except Exception as e:
        print(f"[KAMIS fetch error] {e}")
        return None


@app.route("/api/market", methods=["GET"])
@login_required
def api_market():
    today = date.today()
    req_date = request.args.get("date", "").strip()
    if req_date:
        try:
            regday_obj = date.fromisoformat(req_date)
        except ValueError:
            return jsonify({"ok": False, "msg": "날짜 형식이 올바르지 않습니다. (YYYY-MM-DD)"}), 400
        if regday_obj > today:
            return jsonify({"ok": False, "msg": "오늘 이후 날짜는 조회할 수 없습니다."}), 400
        if regday_obj < MARKET_MIN_DATE:
            return jsonify({"ok": False, "msg": "조회 가능한 최소 날짜는 2020-01-01 입니다."}), 400
    else:
        regday_obj = today
    regday = regday_obj.isoformat()

    is_today = regday == today.isoformat()
    records = MarketPriceRecord.query.filter_by(regday=regday).all()
    stale = (
        not records
        or (is_today and records and (datetime.utcnow() - records[0].fetched_at).total_seconds() > 3600)
    )
    if stale:
        data = fetch_kamis_prices(regday)
        if data is None:
            data = _mock_market_data(regday)
        for item in data:
            row = MarketPriceRecord.query.filter_by(regday=regday, name=item["name"]).first()
            if row is None:
                row = MarketPriceRecord(regday=regday, name=item["name"])
                db.session.add(row)
            row.unit = item["unit"]
            row.price = item["price"]
            row.change_pct = item["change_pct"]
            row.trend = item["trend"]
            row.source = item["source"]
            row.fetched_at = datetime.utcnow()
        db.session.commit()
        records = MarketPriceRecord.query.filter_by(regday=regday).all()

    order = {it["name"]: idx for idx, it in enumerate(MARKET_ITEMS)}
    records.sort(key=lambda r: order.get(r.name, 999))
    return jsonify({"ok": True, "data": [r.to_dict() for r in records], "date": regday})


@app.route("/api/market/history", methods=["GET"])
@login_required
def api_market_history():
    """특정 품목의 최근 N일(기본 30일) 가격 히스토리를 반환한다."""
    name = request.args.get("name", "").strip()
    if not name:
        return jsonify({"ok": False, "msg": "name 파라미터가 필요합니다."}), 400
    days = min(int(request.args.get("days", 30) or 30), 365)
    rows = (
        MarketPriceRecord.query.filter_by(name=name)
        .order_by(MarketPriceRecord.regday.desc())
        .limit(days)
        .all()
    )
    rows.sort(key=lambda r: r.regday)
    return jsonify({"ok": True, "name": name, "data": [
        {"date": r.regday, "price": r.price, "change_pct": r.change_pct, "source": r.source} for r in rows
    ]})


# ----------------------------------------------------------------------
# 날씨 예보 (Weather) - 모의 데이터
# ----------------------------------------------------------------------
WEATHER_ICONS = ["맑음", "구름조금", "흐림", "비", "소나기", "눈"]


@app.route("/api/weather", methods=["GET"])
@login_required
def api_weather():
    region = request.args.get("region", "전국")
    today = date.today()
    forecast = []
    random.seed(today.toordinal() + len(region))
    for i in range(7):
        d = today + timedelta(days=i)
        forecast.append({
            "date": d.isoformat(),
            "day": ["월", "화", "수", "목", "금", "토", "일"][d.weekday()],
            "condition": random.choice(WEATHER_ICONS),
            "temp_max": random.randint(18, 33),
            "temp_min": random.randint(8, 20),
            "humidity": random.randint(40, 90),
            "rain_prob": random.randint(0, 90),
        })
    random.seed()
    return jsonify({"ok": True, "region": region, "data": forecast})


# ----------------------------------------------------------------------
# 농약 정보 (Pesticide Info) - 정적 참고 데이터
# ----------------------------------------------------------------------
PESTICIDE_DB = [
    {"name": "이미다클로프리드 수화제", "type": "살충제", "target": "진딧물, 응애",
     "crops": "벼, 배추, 고추", "safety_period": "7일", "dilution": "2,000배"},
    {"name": "만코제브 수화제", "type": "살균제", "target": "탄저병, 노균병",
     "crops": "고추, 토마토, 배추", "safety_period": "7일", "dilution": "500배"},
    {"name": "글리포세이트 액제", "type": "제초제", "target": "일년생·다년생 잡초",
     "crops": "과수원, 비농경지", "safety_period": "수확 전 사용금지", "dilution": "200배"},
    {"name": "펜토에이트 유제", "type": "살충제", "target": "나방류, 노린재",
     "crops": "과수, 채소류", "safety_period": "10일", "dilution": "1,000배"},
    {"name": "트리아디메폰 수화제", "type": "살균제", "target": "흰가루병, 녹병",
     "crops": "과수, 벼", "safety_period": "14일", "dilution": "2,000배"},
    {"name": "클로르피리포스 유제", "type": "살충제", "target": "굼벵이, 뿌리해충",
     "crops": "감자, 고구마", "safety_period": "21일", "dilution": "1,000배"},
    {"name": "아족시스트로빈 액상수화제", "type": "살균제", "target": "역병, 탄저병",
     "crops": "고추, 감자, 포도", "safety_period": "3일", "dilution": "2,000배"},
]


@app.route("/api/pesticides", methods=["GET"])
@login_required
def api_pesticides():
    q = request.args.get("q", "").strip()
    data = PESTICIDE_DB
    if q:
        data = [p for p in PESTICIDE_DB if q in p["name"] or q in p["target"] or q in p["crops"]]
    return jsonify({"ok": True, "data": data})


# ----------------------------------------------------------------------
# 정부 지원사업 (Government Support Programs) - 정적 참고 데이터
# ----------------------------------------------------------------------
SUPPORT_PROGRAMS = [
    {"title": "청년 후계농 영농정착지원사업", "agency": "농림축산식품부",
     "period": "2026.01.01 ~ 2026.12.31", "target": "만 18~40세 청년농업인",
     "content": "월 최대 110만원 정착지원금 및 창업자금 융자 지원",
     "status": "접수중"},
    {"title": "스마트팜 혁신밸리 청년창업 보육",
     "agency": "농림축산식품부", "period": "2026.03.01 ~ 2026.11.30",
     "target": "스마트팜 창업 희망 청년", "content": "임대형 스마트팜 실습교육 및 초기 정착 지원",
     "status": "접수중"},
    {"title": "친환경농업 direct 지불금", "agency": "농림축산식품부",
     "period": "상시", "target": "친환경 인증 농업인",
     "content": "친환경 인증 유지 농가 대상 직불금 지급", "status": "상시접수"},
    {"title": "농기계 임대사업", "agency": "지자체 농업기술센터",
     "period": "연중", "target": "관내 등록 농업인",
     "content": "트랙터, 이앙기 등 농기계 저렴한 비용으로 임대", "status": "상시접수"},
    {"title": "농업재해보험 보험료 지원", "agency": "NH농협손해보험",
     "period": "작목별 상이", "target": "전체 농업인",
     "content": "보험료의 최대 50% 국비·지방비 지원", "status": "접수중"},
    {"title": "농산물 산지유통시설 현대화 지원", "agency": "농림축산식품부",
     "period": "2026.02.01 ~ 2026.06.30", "target": "농업법인, 작목반",
     "content": "저온저장고, 선별기 등 유통시설 구축비 지원", "status": "접수중"},
]


@app.route("/api/support-programs", methods=["GET"])
@login_required
def api_support_programs():
    return jsonify({"ok": True, "data": SUPPORT_PROGRAMS})


# ----------------------------------------------------------------------
# 농작업 안전 (Farm Work Safety) - 정적 안전 수칙 데이터
# ----------------------------------------------------------------------
SAFETY_GUIDES = [
    {"category": "농기계 안전", "title": "경운기·트랙터 전복 사고 예방",
     "content": "경사지 작업 시 저속 운행하고, 급회전과 급제동을 피하세요. "
                "탑승석 외에 사람을 태우지 마세요."},
    {"category": "농약 안전", "title": "농약 살포 시 보호장비 착용",
     "content": "방제복, 마스크, 보안경, 장갑을 반드시 착용하고 바람을 등지고 살포하세요. "
                "살포 후 즉시 손과 얼굴을 씻으세요."},
    {"category": "온열질환 예방", "title": "폭염 시 농작업 안전수칙",
     "content": "낮 12시~17시 작업을 피하고, 2시간마다 그늘에서 휴식하며 물을 충분히 섭취하세요."},
    {"category": "밀폐공간 안전", "title": "저장고·퇴비사 질식사고 예방",
     "content": "밀폐된 저장시설 출입 전 충분히 환기하고, 유해가스 감지기를 사용하세요."},
    {"category": "추락 안전", "title": "과수원 고소작업 추락 예방",
     "content": "안전한 사다리와 작업대를 사용하고, 2인 1조로 작업하세요."},
    {"category": "예초기 안전", "title": "예초기 사용 시 안전수칙",
     "content": "보호안경과 안전화를 착용하고, 반경 15m 이내 사람 접근을 통제하세요."},
]


@app.route("/api/safety", methods=["GET"])
@login_required
def api_safety():
    return jsonify({"ok": True, "data": SAFETY_GUIDES})


# ----------------------------------------------------------------------
# 대시보드 요약 (Dashboard Summary)
# ----------------------------------------------------------------------
@app.route("/api/dashboard/summary", methods=["GET"])
@login_required
def api_dashboard_summary():
    crop_q = owned_query(Crop)
    task_q = owned_query(Task)
    inv_q = owned_query(Inventory)
    ship_q = owned_query(Shipment)
    journal_q = owned_query(Journal)

    total_crops = crop_q.count()
    growing_crops = crop_q.filter_by(status="재배중").count()
    pending_tasks = task_q.filter(Task.status != "완료").count()
    today_str = date.today().isoformat()
    today_tasks = task_q.filter(Task.due_date == today_str).count()
    low_stock = inv_q.filter(Inventory.quantity <= 5).count()
    total_shipment_amount = 0
    for s in ship_q.all():
        total_shipment_amount += (s.quantity or 0) * (s.unit_price or 0)

    recent_journals = journal_q.order_by(Journal.created_at.desc()).limit(5).all()
    upcoming_tasks = task_q.filter(Task.status != "완료").order_by(Task.due_date.asc()).limit(5).all()

    # 최근 7일 작업일지 통계 (차트용)
    chart_labels = []
    chart_counts = []
    for i in range(6, -1, -1):
        d = date.today() - timedelta(days=i)
        chart_labels.append(d.strftime("%m/%d"))
        cnt = journal_q.filter(Journal.date == d.isoformat()).count()
        chart_counts.append(cnt)

    crop_status_counts = {}
    for c in crop_q.all():
        crop_status_counts[c.status] = crop_status_counts.get(c.status, 0) + 1

    return jsonify({
        "ok": True,
        "data": {
            "total_crops": total_crops,
            "growing_crops": growing_crops,
            "pending_tasks": pending_tasks,
            "today_tasks": today_tasks,
            "low_stock": low_stock,
            "total_shipment_amount": total_shipment_amount,
            "recent_journals": [j.to_dict() for j in recent_journals],
            "upcoming_tasks": [t.to_dict() for t in upcoming_tasks],
            "chart_labels": chart_labels,
            "chart_counts": chart_counts,
            "crop_status_counts": crop_status_counts,
        }
    })


# ----------------------------------------------------------------------
# 시드 데이터 (Seed Data)
# ----------------------------------------------------------------------
def seed_data():
    if User.query.first():
        return  # 이미 초기화됨

    # 등급 (Grades) 시드 데이터
    grades = [
        Grade(code="general", name="일반회원", discount_percent=0, min_spend=0,
              color="#8a9a8a", display_order=1, description="가입 시 기본으로 부여되는 등급입니다."),
        Grade(code="excellent", name="우수회원", discount_percent=5, min_spend=100000,
              color="#4caf7d", display_order=2, description="활발한 이용 실적을 가진 우수 회원 등급입니다."),
        Grade(code="vip", name="VIP", discount_percent=10, min_spend=500000,
              color="#2f8f5b", display_order=3, description="요금제 이용료 10% 할인 혜택이 제공됩니다."),
        Grade(code="vvip", name="VVIP", discount_percent=20, min_spend=1500000,
              color="#1f6b43", display_order=4, description="최상위 회원 등급으로 20% 할인 혜택이 제공됩니다."),
        Grade(code="admin", name="관리자", discount_percent=100, min_spend=0,
              color="#2e5233", display_order=5, description="시스템 관리자 등급입니다."),
    ]
    db.session.add_all(grades)
    db.session.commit()
    general_grade, excellent_grade, vip_grade, vvip_grade, admin_grade = grades

    admin = User(name="관리자", email="cksdudd102@naver.com", role="admin",
                 phone="010-1234-5678", farm_name="스마트팜 운영본부", region="세종특별자치시",
                 grade_id=admin_grade.id)
    admin.set_password("1q2w3e4r~@")

    farmer = User(name="김농부", email="farmer@farm.com", role="farmer",
                  phone="010-9876-5432", farm_name="행복한 농장", region="전라남도 나주시",
                  grade_id=vip_grade.id)
    farmer.set_password("farm1234")

    farmer2 = User(name="이농부", email="farmer2@farm.com", role="farmer",
                   phone="010-2222-3333", farm_name="푸른들녘 농장", region="충청북도 청주시",
                   grade_id=excellent_grade.id)
    farmer2.set_password("farm1234")

    farmer3 = User(name="박농부", email="farmer3@farm.com", role="farmer",
                   phone="010-4444-5555", farm_name="드넓은 농장", region="경상북도 상주시",
                   grade_id=general_grade.id)
    farmer3.set_password("farm1234")

    farmer4 = User(name="최농부", email="farmer4@farm.com", role="farmer",
                   phone="010-6666-7777", farm_name="희망찬 농장", region="강원특별자치도 춘천시",
                   grade_id=general_grade.id)
    farmer4.set_password("farm1234")

    db.session.add_all([admin, farmer, farmer2, farmer3, farmer4])
    db.session.commit()


    today = date.today()

    # 요금제 (Plans) 시드 데이터
    plans = [
        Plan(code="free", name="무료", price_monthly=0, price_annual=0,
             display_order=1, is_active=True,
             features=json.dumps([
                 "작물 1개까지 등록", "영농 일지 기본 기능", "작업 일정 관리",
                 "커뮤니티 이용", "기본 시세/날씨 정보 조회"
             ], ensure_ascii=False)),
        Plan(code="starter", name="스타터", price_monthly=29000, price_annual=290000,
             display_order=2, is_active=True,
             features=json.dumps([
                 "작물 5개까지 등록", "영농 일지 무제한 작성", "재고 관리 기능",
                 "AI 작물 진단 월 10회", "출하 관리 기능", "이메일 지원"
             ], ensure_ascii=False)),
        Plan(code="pro", name="프로", price_monthly=49000, price_annual=490000,
             display_order=3, is_active=True,
             features=json.dumps([
                 "작물 무제한 등록", "영농 일지 사진 첨부 무제한", "재고 부족 알림",
                 "AI 작물 진단 무제한", "출하 관리 + 정산 리포트",
                 "우선 고객 지원", "데이터 내보내기(CSV)"
             ], ensure_ascii=False)),
        Plan(code="enterprise", name="기업", price_monthly=99000, price_annual=990000,
             display_order=4, is_active=True,
             features=json.dumps([
                 "프로 요금제 전체 기능 포함", "다중 농장/사용자 관리",
                 "전담 매니저 배정", "맞춤형 리포트 및 통계",
                 "API 연동 지원", "24시간 전화 지원"
             ], ensure_ascii=False)),
    ]
    db.session.add_all(plans)
    db.session.commit()

    free_plan, starter_plan, pro_plan, enterprise_plan = plans

    subscriptions = [
        UserSubscription(user_id=admin.id, plan_id=enterprise_plan.id, billing_cycle="annual",
                          status="active", start_date=(today - timedelta(days=60)).isoformat(),
                          expiry_date=(today + timedelta(days=305)).isoformat()),
        UserSubscription(user_id=farmer.id, plan_id=pro_plan.id, billing_cycle="monthly",
                          status="active", start_date=(today - timedelta(days=10)).isoformat(),
                          expiry_date=(today + timedelta(days=20)).isoformat()),
        UserSubscription(user_id=farmer2.id, plan_id=starter_plan.id, billing_cycle="monthly",
                          status="active", start_date=(today - timedelta(days=5)).isoformat(),
                          expiry_date=(today + timedelta(days=25)).isoformat()),
        UserSubscription(user_id=farmer3.id, plan_id=free_plan.id, billing_cycle="monthly",
                          status="active", start_date=(today - timedelta(days=90)).isoformat(),
                          expiry_date=None),
        UserSubscription(user_id=farmer4.id, plan_id=starter_plan.id, billing_cycle="annual",
                          status="expired", start_date=(today - timedelta(days=400)).isoformat(),
                          expiry_date=(today - timedelta(days=35)).isoformat()),
    ]
    db.session.add_all(subscriptions)
    db.session.commit()

    crops = [
        Crop(user_id=farmer.id, name="배추", variety="가을배추", field_location="1번 밭 (1200평)",
             area=1200, planting_date=(today - timedelta(days=40)).isoformat(),
             expected_harvest_date=(today + timedelta(days=30)).isoformat(),
             status="재배중", memo="정식 후 관수 관리 중"),
        Crop(user_id=farmer.id, name="고추", variety="청양고추", field_location="2번 밭 (800평)",
             area=800, planting_date=(today - timedelta(days=70)).isoformat(),
             expected_harvest_date=(today + timedelta(days=10)).isoformat(),
             status="재배중", memo="탄저병 예방 방제 필요"),
        Crop(user_id=farmer.id, name="벼", variety="신동진", field_location="3번 논 (3000평)",
             area=3000, planting_date=(today - timedelta(days=100)).isoformat(),
             expected_harvest_date=(today + timedelta(days=15)).isoformat(),
             status="재배중", memo="출수기 완료, 등숙 진행중"),
        Crop(user_id=farmer.id, name="감자", variety="수미", field_location="4번 밭 (500평)",
             area=500, planting_date=(today - timedelta(days=90)).isoformat(),
             expected_harvest_date=(today - timedelta(days=5)).isoformat(),
             status="수확완료", memo="수확 완료, 저장고 입고"),
    ]
    db.session.add_all(crops)
    db.session.commit()

    journals = [
        Journal(user_id=farmer.id, crop_id=crops[0].id, date=(today - timedelta(days=2)).isoformat(),
                work_type="관수", weather="맑음", content="점적관수 3시간 실시. 토양 수분 양호."),
        Journal(user_id=farmer.id, crop_id=crops[1].id, date=(today - timedelta(days=1)).isoformat(),
                work_type="방제", weather="흐림", content="탄저병 예방을 위한 살균제 살포 완료."),
        Journal(user_id=farmer.id, crop_id=crops[2].id, date=today.isoformat(),
                work_type="관찰", weather="맑음", content="이삭 상태 양호, 병해충 없음 확인."),
        Journal(user_id=farmer.id, crop_id=crops[0].id, date=(today - timedelta(days=5)).isoformat(),
                work_type="시비", weather="맑음", content="웃거름 요소비료 20kg 살포."),
    ]
    db.session.add_all(journals)

    tasks = [
        Task(user_id=farmer.id, crop_id=crops[1].id, title="고추 탄저병 방제 재실시",
             memo="일주일 후 재방제 필요", due_date=(today + timedelta(days=3)).isoformat(),
             priority="높음", status="예정"),
        Task(user_id=farmer.id, crop_id=crops[0].id, title="배추 웃거름 주기",
             memo="요소비료 준비", due_date=(today + timedelta(days=1)).isoformat(),
             priority="보통", status="예정"),
        Task(user_id=farmer.id, crop_id=crops[2].id, title="벼 수확 일정 조율",
             memo="콤바인 임대 예약", due_date=(today + timedelta(days=14)).isoformat(),
             priority="높음", status="예정"),
        Task(user_id=farmer.id, crop_id=None, title="농기계 정기 점검",
             memo="트랙터, 이앙기 엔진오일 교체", due_date=today.isoformat(),
             priority="보통", status="완료"),
        Task(user_id=farmer.id, crop_id=crops[3].id, title="감자 저장고 온도 점검",
             memo="적정온도 4도 유지", due_date=(today - timedelta(days=1)).isoformat(),
             priority="낮음", status="완료"),
    ]
    db.session.add_all(tasks)

    inventory = [
        Inventory(user_id=farmer.id, name="요소비료", category="비료", quantity=45, unit="kg",
                  location="농자재 창고 A", expiry_date=(today + timedelta(days=365)).isoformat(),
                  memo="봉지 재고"),
        Inventory(user_id=farmer.id, name="탄저병 살균제", category="농약", quantity=3, unit="병",
                  location="농약 보관함", expiry_date=(today + timedelta(days=200)).isoformat(),
                  memo="재고 부족 - 추가 구매 필요"),
        Inventory(user_id=farmer.id, name="배추 종자", category="종자", quantity=2, unit="봉",
                  location="냉장 보관", expiry_date=(today + timedelta(days=300)).isoformat(),
                  memo=""),
        Inventory(user_id=farmer.id, name="멀칭비닐", category="농자재", quantity=12, unit="롤",
                  location="농자재 창고 B", expiry_date=None, memo="차기작 대비 보유"),
        Inventory(user_id=farmer.id, name="응애 전용 살충제", category="농약", quantity=1, unit="병",
                  location="농약 보관함", expiry_date=(today + timedelta(days=150)).isoformat(),
                  memo="재고 부족"),
    ]
    db.session.add_all(inventory)

    shipments = [
        Shipment(user_id=farmer.id, crop_id=crops[3].id, buyer="농협 공판장",
                 quantity=2000, unit="kg", unit_price=2600,
                 shipment_date=(today - timedelta(days=3)).isoformat(), status="정산완료",
                 memo="1등급 판정"),
        Shipment(user_id=farmer.id, crop_id=crops[1].id, buyer="지역 로컬푸드 직매장",
                 quantity=150, unit="kg", unit_price=8500,
                 shipment_date=(today + timedelta(days=12)).isoformat(), status="예정",
                 memo="예약 출하"),
    ]
    db.session.add_all(shipments)

    posts = [
        Post(user_id=farmer.id, category="정보공유", title="가을배추 정식 후 관수 팁 공유합니다",
             content="정식 초기 2주간은 점적관수로 매일 30분씩 주는게 활착에 좋았습니다. "
                     "참고하세요!", views=23),
        Post(user_id=admin.id, category="공지", title="스마트팜 웹앱 오픈 안내",
             content="영농 관리를 더 편리하게! 작물관리, 일지, 시세조회까지 한번에 이용해보세요.",
             views=57),
        Post(user_id=farmer.id, category="질문", title="고추 탄저병 방제 주기 문의드립니다",
             content="장마철 이후 탄저병이 계속 발생하는데 방제 주기를 어떻게 잡으시나요?",
             views=15),
    ]
    db.session.add_all(posts)

    rda_notices = [
        RdaNotice(title="2026년 벼 재배 안전 영농 지침 발표", category="영농정보",
                  notice_date=(today - timedelta(days=2)).isoformat(),
                  content="농촌진흥청은 이상기후에 대응한 벼 재배 관리 요령을 발표했습니다. "
                          "적기 이앙과 물관리가 중요합니다.",
                  source_url="https://www.rda.go.kr"),
        RdaNotice(title="여름철 폭염 대비 농작물 관리요령", category="기상정보",
                  notice_date=(today - timedelta(days=5)).isoformat(),
                  content="고온 피해 예방을 위해 차광막 설치와 관수 관리를 철저히 해야 합니다.",
                  source_url="https://www.rda.go.kr"),
        RdaNotice(title="스마트팜 확산을 위한 청년농업인 교육 실시", category="교육안내",
                  notice_date=(today - timedelta(days=10)).isoformat(),
                  content="농촌진흥청 산하 기관에서 스마트팜 실습교육 신청을 받습니다.",
                  source_url="https://www.rda.go.kr"),
        RdaNotice(title="병해충 예찰정보 - 가을철 배추 무름병 주의", category="병해충정보",
                  notice_date=(today - timedelta(days=1)).isoformat(),
                  content="최근 잦은 강우로 배추 무름병 발생 위험이 높아 예방적 방제가 필요합니다.",
                  source_url="https://www.rda.go.kr"),
    ]
    db.session.add_all(rda_notices)

    promo_codes = [
        PromoCode(code="WELCOME2026", discount_percent=10,
                  description="신규 회원 환영 프로모션 - 요금제 10% 할인",
                  is_active=True, max_uses=0, expiry_date=(today + timedelta(days=180)).isoformat()),
        PromoCode(code="FARM50", discount_percent=50,
                  description="특별 프로모션 - 요금제 50% 할인 (선착순 100명)",
                  is_active=True, max_uses=100, expiry_date=(today + timedelta(days=30)).isoformat()),
        PromoCode(code="EXPIRED10", discount_percent=10,
                  description="만료된 프로모션 코드 (테스트용)",
                  is_active=True, max_uses=0, expiry_date=(today - timedelta(days=10)).isoformat()),
    ]
    db.session.add_all(promo_codes)

    links = [
        Link(title="농촌진흥청", url="https://www.rda.go.kr", category="공공기관",
             description="농업 기술 연구 및 보급을 담당하는 정부기관", display_order=1),
        Link(title="농림축산식품부", url="https://www.mafra.go.kr", category="공공기관",
             description="농림축산식품 정책 총괄 부처", display_order=2),
        Link(title="농사로", url="https://www.nongsaro.go.kr", category="공공기관",
             description="농업기술 정보포털", display_order=3),
        Link(title="농수산물유통정보(KAMIS)", url="https://www.kamis.or.kr", category="시세정보",
             description="농산물 도소매 가격 정보 제공", display_order=1),
        Link(title="한국농수산식품유통공사(aT)", url="https://www.at.or.kr", category="시세정보",
             description="농수산식품 유통 및 수출입 지원기관", display_order=2),
        Link(title="농업정책보험금융원", url="https://www.apfs.kr", category="금융/보험",
             description="농업정책자금 및 농작물재해보험 안내", display_order=1),
        Link(title="NH농협은행", url="https://www.nonghyup.com", category="금융/보험",
             description="농업인 특화 금융 서비스", display_order=2),
        Link(title="기상청 농업기상정보", url="https://www.weather.go.kr", category="기상정보",
             description="농업 특화 기상 예보 및 특보", display_order=1),
        Link(title="농업기술포털 흙토람", url="https://soil.rda.go.kr", category="기술정보",
             description="토양 및 시비처방 정보 제공", display_order=1),
        Link(title="스마트팜코리아", url="https://www.smartfarmkorea.net", category="기술정보",
             description="스마트팜 관련 정보 및 교육", display_order=2),
    ]
    db.session.add_all(links)

    db.session.commit()
    print(">> 시드 데이터 생성 완료")


# ----------------------------------------------------------------------
# 앱 초기화
# ----------------------------------------------------------------------
with app.app_context():
    db.create_all()

    def _ensure_column(table, column, ddl):
        try:
            existing = {c["name"] for c in db.inspect(db.engine).get_columns(table)}
            if column not in existing:
                db.session.execute(db.text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
                db.session.commit()
                print(f">> {table}.{column} 컬럼 추가 완료")
        except Exception as e:
            db.session.rollback()
            print(f">> 컬럼 마이그레이션 실패 ({table}.{column}): {e}")

    _ensure_column("crops", "is_public", "BOOLEAN DEFAULT FALSE NOT NULL")
    _ensure_column("journals", "is_public", "BOOLEAN DEFAULT FALSE NOT NULL")
    _ensure_column("tasks", "is_public", "BOOLEAN DEFAULT FALSE NOT NULL")

    seed_data()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
