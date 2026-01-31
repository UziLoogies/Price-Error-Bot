"""Collect and manage feedback on LLM outputs."""

import hashlib
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.db.models import LLMFeedback, Product

logger = logging.getLogger(__name__)


class FeedbackCollector:
    """
    Collect user feedback on LLM outputs.
    
    Features:
    - Store LLM outputs and user corrections
    - Track accuracy metrics
    - Prepare data for fine-tuning
    """
    
    async def record_feedback(
        self,
        db: AsyncSession,
        product_id: Optional[int],
        llm_output: Dict[str, Any],
        task_type: str,
        model_name: str,
        prompt_hash: Optional[str] = None,
        user_correction: Optional[Dict[str, Any]] = None,
        is_correct: Optional[bool] = None,
        feedback_notes: Optional[str] = None,
    ) -> LLMFeedback:
        """
        Record feedback on an LLM output.
        
        Args:
            db: Database session
            product_id: Optional product ID
            llm_output: LLM output dictionary
            task_type: Type of task (e.g., 'anomaly_review', 'attribute_extraction')
            model_name: Model name used
            prompt_hash: Optional hash of prompt
            user_correction: Optional user correction
            is_correct: Whether the output was correct
            feedback_notes: Optional feedback notes
            
        Returns:
            Created LLMFeedback record
        """
        feedback = LLMFeedback(
            product_id=product_id,
            llm_output=llm_output,
            user_correction=user_correction,
            task_type=task_type,
            prompt_hash=prompt_hash,
            model_name=model_name,
            is_correct=is_correct,
            feedback_notes=feedback_notes,
        )
        
        db.add(feedback)
        await db.commit()
        await db.refresh(feedback)
        
        logger.info(f"Recorded feedback for {task_type} task (ID: {feedback.id})")
        
        return feedback
    
    async def get_accuracy_stats(
        self,
        db: AsyncSession,
        task_type: Optional[str] = None,
        model_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get accuracy statistics for LLM outputs.
        
        Args:
            db: Database session
            task_type: Optional task type filter
            model_name: Optional model name filter
            
        Returns:
            Dictionary with accuracy statistics
        """
        query = select(LLMFeedback)
        
        if task_type:
            query = query.where(LLMFeedback.task_type == task_type)
        if model_name:
            query = query.where(LLMFeedback.model_name == model_name)
        
        result = await db.execute(query)
        all_feedback = result.scalars().all()
        
        total = len(all_feedback)
        with_feedback = [f for f in all_feedback if f.is_correct is not None]
        correct = sum(1 for f in with_feedback if f.is_correct)
        incorrect = len(with_feedback) - correct
        
        accuracy = correct / len(with_feedback) if with_feedback else 0.0
        
        return {
            "total_feedback": total,
            "with_validation": len(with_feedback),
            "correct": correct,
            "incorrect": incorrect,
            "accuracy": accuracy,
        }
    
    async def get_fine_tuning_data(
        self,
        db: AsyncSession,
        task_type: str,
        model_name: str,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get data formatted for fine-tuning.
        
        Args:
            db: Database session
            task_type: Task type
            model_name: Model name
            limit: Optional limit on number of records
            
        Returns:
            List of fine-tuning examples
        """
        query = select(LLMFeedback).where(
            LLMFeedback.task_type == task_type,
            LLMFeedback.model_name == model_name,
            LLMFeedback.user_correction.isnot(None),  # Only examples with corrections
        ).order_by(LLMFeedback.created_at.desc())
        
        if limit:
            query = query.limit(limit)
        
        result = await db.execute(query)
        feedbacks = result.scalars().all()
        
        examples = []
        for feedback in feedbacks:
            examples.append({
                "input": feedback.llm_output,  # Original output
                "output": feedback.user_correction,  # Corrected output
                "notes": feedback.feedback_notes,
            })
        
        return examples
    
    @staticmethod
    def hash_prompt(prompt: str) -> str:
        """Generate hash of prompt for tracking."""
        return hashlib.sha256(prompt.encode('utf-8')).hexdigest()


# Global feedback collector instance
feedback_collector = FeedbackCollector()
