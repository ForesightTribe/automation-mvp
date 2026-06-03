import React from "react";
import { Outlet, NavLink } from "react-router-dom";
import { ROUTES } from "../utils/constants";

const AppLayout = () => {
  return (
    <div style={{ display: "flex", minHeight: "100vh" }}>
      <aside style={{ width: 220, background: "#111", color: "#fff", padding: 16 }}>
        <div style={{ fontWeight: 700, fontSize: 18, marginBottom: 32 }}>Foresight</div>
        <nav style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <NavLink to={ROUTES.DASHBOARD} end style={navStyle}>Dashboard</NavLink>
          <NavLink to={ROUTES.ANALYTICS} style={navStyle}>Analytics</NavLink>
          <NavLink to={ROUTES.PRODUCTS} style={navStyle}>Products</NavLink>
          <NavLink to={ROUTES.INVENTORY} style={navStyle}>Inventory</NavLink>
          <NavLink to={ROUTES.ADS} style={navStyle}>Ads</NavLink>
        </nav>
      </aside>
      <main style={{ flex: 1, padding: 24, background: "#f9fafb" }}>
        <Outlet />
      </main>
    </div>
  );
};

const navStyle = ({ isActive }) => ({
  color: isActive ? "#fff" : "#aaa",
  textDecoration: "none",
  padding: "8px 12px",
  borderRadius: 6,
  background: isActive ? "#333" : "transparent",
});

export default AppLayout;
