import React from "react";
import { Outlet } from "react-router-dom";

const AuthLayout = () => {
  return (
    <div style={{ display: "flex", justifyContent: "center", alignItems: "center", minHeight: "100vh", background: "#f9fafb" }}>
      <Outlet />
    </div>
  );
};

export default AuthLayout;
