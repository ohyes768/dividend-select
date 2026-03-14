"""
更新 PE 数据
"""
from src.services.pe_service import get_pe_service

if __name__ == "__main__":
    pe_service = get_pe_service()
    count = pe_service.update_pe_data()
    print(f"PE 数据更新完成，共 {count} 条记录")