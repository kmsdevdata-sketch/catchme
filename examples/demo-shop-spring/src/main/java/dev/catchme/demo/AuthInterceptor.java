package dev.catchme.demo;

import io.jsonwebtoken.Jwts;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpStatus;
import org.springframework.web.servlet.HandlerInterceptor;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

@Configuration
public class AuthInterceptor implements HandlerInterceptor, WebMvcConfigurer {
    static final String ATTR = "catchme.userId";

    static long userId(HttpServletRequest req) {
        return (Long) req.getAttribute(ATTR);
    }

    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        registry.addInterceptor(this).addPathPatterns("/orders", "/orders/**");
    }

    @Override
    public boolean preHandle(HttpServletRequest req, HttpServletResponse res, Object handler) throws Exception {
        String header = req.getHeader("Authorization");
        if (header == null || !header.startsWith("Bearer ")) {
            res.sendError(HttpStatus.UNAUTHORIZED.value(), "missing token");
            return false;
        }
        try {
            var claims = Jwts.parser().verifyWith(ShopController.KEY).build()
                    .parseSignedClaims(header.substring(7)).getPayload();
            req.setAttribute(ATTR, Long.valueOf(claims.getSubject()));
            return true;
        } catch (Exception e) {
            res.sendError(HttpStatus.UNAUTHORIZED.value(), "invalid token");
            return false;
        }
    }
}
