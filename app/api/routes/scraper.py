from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.services import scraper_service

router = APIRouter()

@router.post("/companies")
def sync_companies(db: Session = Depends(get_db)):
    """Sync companies from local Excel file into database"""
    try:
        result = scraper_service.sync_companies_from_excel(db)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/historical")
def sync_historical(db: Session = Depends(get_db)):
    """Fetch 1 year historical data for all companies from Yahoo Finance"""
    try:
        result = scraper_service.fetch_historical_data_yfinance(db)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/daily")
def sync_daily(db: Session = Depends(get_db)):
    """Fetch daily data for all companies from IDX"""
    try:
        result = scraper_service.fetch_daily_data_idx(db)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


